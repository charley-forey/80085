"""Structured logs and OpenTelemetry (spec section 33).

**What is actually traced.** HTTP requests to the API, auto-instrumented; the
four stages of `recall` (embedding, lexical query, vector query, ranking); and
the worker's lease -> run -> report loop. That is enough to answer the question
this exists to answer -- *which part was slow* -- without reading it off a
single aggregate number.

**What is not.** Spec section 33 asks for one trace that follows a request from
MCP through the API, retrieval, ranking, the queue, the worker, the sandbox,
verification and reputation. This is not that trace. The queue is a Postgres
table and nothing carries trace context across it, so the worker's spans start
a new trace rather than continuing the caller's; MCP, the sandbox, the
verifiers and reputation carry no spans of their own. Joining the two halves
needs a `traceparent` column on `executions` and a propagator on both sides --
a schema change, deliberately not made yet.

**Metrics** (spec section 33 names rates; these are the raw counts a rate is
computed from, which is how OTel expects it):

* `recall_requests{matched}` -> `recall_match_rate`
* `executions_completed{status, verified, cross_organization}` ->
  `execution_success_rate`, `verification_success_rate`,
  `successful_reuse_rate`, `cross_agent_reuse_rate`
* `queue_depth` -> the backlog waiting for a worker
* `lease_reclaims{outcome}` -> how often a worker dies holding a claim

Exporting is opt-in. With no OTLP endpoint configured **no provider is
installed at all**: the API's no-op tracer and meter answer, spans are never
allocated and instruments never record. Local development needs no collector
and pays nothing for the instrumentation being there.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import structlog
from opentelemetry import metrics, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from boobs_common.config import settings

_CONFIGURED = False


def _signal_endpoint(endpoint: str, signal: str) -> str:
    """OTEL_EXPORTER_OTLP_ENDPOINT is a base URL; each signal hangs off it.

    Passing the base straight to an exporter posts traces and metrics to the
    same path, which no collector accepts.
    """
    base = endpoint.rstrip("/")
    return base if base.endswith(f"/v1/{signal}") else f"{base}/v1/{signal}"


def configure(service_name: str) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(
        format="%(message)s", level=getattr(logging, settings().log_level.upper(), logging.INFO)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings().log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )

    endpoint = settings().otel_exporter_otlp_endpoint
    if endpoint:
        # Only installed when there is somewhere to send the data. An SDK
        # provider with no exporter still allocates a real Span for every
        # `start_as_current_span` on the recall path; the no-op does not.
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        resource = Resource.create({"service.name": service_name})
        traces = TracerProvider(resource=resource)
        traces.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=_signal_endpoint(endpoint, "traces")))
        )
        trace.set_tracer_provider(traces)
        metrics.set_meter_provider(
            MeterProvider(
                resource=resource,
                metric_readers=[
                    PeriodicExportingMetricReader(
                        OTLPMetricExporter(endpoint=_signal_endpoint(endpoint, "metrics"))
                    )
                ],
            )
        )
    _CONFIGURED = True


def instrument_fastapi(app: Any) -> bool:
    """Auto-instrument an ASGI app, if there is anywhere to send the spans.

    Returns whether instrumentation was installed, which is the only honest
    thing to assert in a test. Opt-in on the same setting as the exporter: an
    unconfigured deployment gets no extra middleware and no extra latency.

    Health and readiness are excluded. A platform probes them every few seconds
    forever, and that volume would bury the requests anyone actually wants to
    look at.
    """
    if not settings().otel_exporter_otlp_endpoint:
        return False
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/v1/health,/v1/ready")
    return True


def logger(name: str) -> Any:
    return structlog.get_logger(name)


def tracer(name: str) -> trace.Tracer:
    """Safe to call at import time: with no provider installed this returns a
    proxy that resolves to the real tracer if `configure` later installs one."""
    return trace.get_tracer(name)


@lru_cache
def _meter() -> metrics.Meter:
    return metrics.get_meter("80085")


@lru_cache
def counter(name: str, description: str = "") -> metrics.Counter:
    """Product metrics from spec section 33: see the catalogue in the module
    docstring for which instrument derives which rate."""
    return _meter().create_counter(name, description=description)


@lru_cache
def histogram(name: str, unit: str = "ms", description: str = "") -> metrics.Histogram:
    return _meter().create_histogram(name, unit=unit, description=description)


@lru_cache
def gauge(name: str, unit: str = "", description: str = "") -> metrics._Gauge:
    """A value that is sampled rather than accumulated -- queue depth, not a
    count of events. `_Gauge` is private only because the API has not settled
    the public alias; `create_gauge` itself is stable."""
    return _meter().create_gauge(name, unit=unit, description=description)

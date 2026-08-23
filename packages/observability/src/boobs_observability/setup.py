"""Structured logs and OpenTelemetry (spec section 33).

One trace should follow a request from MCP through the API, retrieval,
ranking, the queue, the worker, the sandbox, verification and reputation.
Exporting is opt-in: with no OTLP endpoint configured the SDK stays in-process
so local development needs no collector.
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

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    endpoint = settings().otel_exporter_otlp_endpoint
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _CONFIGURED = True


def logger(name: str) -> Any:
    return structlog.get_logger(name)


def tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


@lru_cache
def _meter() -> metrics.Meter:
    return metrics.get_meter("80085")


@lru_cache
def counter(name: str, description: str = "") -> metrics.Counter:
    """Product metrics from spec section 33: recall_match_rate,
    successful_reuse_rate, cross_agent_reuse_rate and friends."""
    return _meter().create_counter(name, description=description)


@lru_cache
def histogram(name: str, unit: str = "ms", description: str = "") -> metrics.Histogram:
    return _meter().create_histogram(name, unit=unit, description=description)

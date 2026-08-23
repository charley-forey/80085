"""Observability is either real or it is a lie about itself.

The module claimed a trace that followed a request end to end while emitting
zero spans, because `tracer()`, `counter()` and `histogram()` had no callers
anywhere. These tests exist so that cannot come back: they assert the spans and
the instruments that the docstring now claims, and nothing more.

Two properties, both of which matter:

* configured, the stages of recall and the worker loop produce named spans and
  the product metrics record;
* unconfigured, no provider is installed, no span is allocated, and every code
  path still runs.

Providers are installed once at import. OpenTelemetry refuses to replace a
global provider after it is set, so a per-test fixture would silently stop
exporting and these tests would pass while proving nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from boobs_api import leases
from boobs_common.config import settings
from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import Principal, RecallQuery, SandboxResult
from boobs_observability import counter, instrument_fastapi
from boobs_observability.setup import _signal_endpoint
from boobs_retrieval.embedding import HashingEmbedder
from boobs_retrieval.pipeline import recall
from boobs_security.keys import Scope

SPANS = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(SPANS))
trace.set_tracer_provider(_provider)

METRICS = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[METRICS]))

PRINCIPAL = Principal(
    organization_id="org_test",
    agent_id="agt_test",
    scopes=frozenset({Scope.EXPERIENCES_READ}),
)


class _Result:
    """Enough of a SQLAlchemy Result for the queries under test."""

    def all(self) -> list[Any]:
        return []

    def scalars(self) -> list[Any]:
        return []


class _Session:
    """A database that answers everything with nothing.

    Spans and counters are the subject here; whether Postgres returns rows is
    covered by the integration suite.
    """

    async def execute(self, *_: Any, **__: Any) -> _Result:
        return _Result()


def span_names() -> set[str]:
    return {span.name for span in SPANS.get_finished_spans()}


# ------------------------------------------------------------------- tracing


async def test_recall_emits_a_span_for_each_stage() -> None:
    """The point of the exercise: a slow recall must name which stage was slow.

    One aggregate `took_ms` cannot distinguish a cold embedder from a slow
    vector query, which is the distinction anyone debugging recall needs.
    """
    SPANS.clear()

    await recall(
        _Session(),  # type: ignore[arg-type]
        PRINCIPAL,
        RecallQuery(task="convert a csv file to json"),
        model=HashingEmbedder(),
    )

    assert {"recall", "recall.embed", "recall.lexical", "recall.vector", "recall.rank"} <= (
        span_names()
    )


async def test_the_embed_span_names_the_embedder_in_use() -> None:
    """A degraded embedder has to be readable off the trace, not just the logs."""
    SPANS.clear()

    await recall(
        _Session(),  # type: ignore[arg-type]
        PRINCIPAL,
        RecallQuery(task="render a chart from a csv"),
        model=HashingEmbedder(),
    )

    embed = next(span for span in SPANS.get_finished_spans() if span.name == "recall.embed")
    assert (embed.attributes or {})["recall.embedder"] == "HashingEmbedder"


JOB = {
    "execution_id": "exe_1",
    "image": "registry/80085/csv_to_json@sha256:" + "0" * 64,
    "command": ["python", "main.py"],
}


class _FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _FakeApi:
    """Serves exactly one job, then stops the worker."""

    base_url = "http://api.invalid"

    def __init__(self, stop: Any) -> None:
        self._served = False
        self._stop = stop

    async def __aenter__(self) -> _FakeApi:
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def post(self, url: str, json: Any = None) -> _FakeResponse:
        if url.endswith("/lease"):
            if self._served:
                self._stop.set()
                return _FakeResponse({"job": None})
            self._served = True
            return _FakeResponse({"job": JOB})
        return _FakeResponse({"status": "succeeded", "verified": True})


class _FakeRuntime:
    async def execute(self, request: Any) -> SandboxResult:
        return SandboxResult(status=ExecutionStatus.SUCCEEDED, exit_code=0, duration_ms=7)


async def test_worker_spans_cover_lease_run_and_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker loop is the other blind spot: off-platform, and the only
    place that knows how long a sandbox actually took.

    Driven through the real `loop()` rather than by replaying span names, which
    would assert nothing about the worker.
    """
    import boobs_worker.main as worker

    monkeypatch.setattr(worker, "runtime", _FakeRuntime())
    monkeypatch.setattr(worker, "client", lambda: _FakeApi(worker._stopping))
    worker._stopping.clear()

    SPANS.clear()
    try:
        await worker.loop()
    finally:
        worker._stopping.clear()

    assert {"worker.lease", "worker.job", "worker.run", "worker.report"} <= span_names()
    run = next(span for span in SPANS.get_finished_spans() if span.name == "worker.run")
    assert (run.attributes or {})["execution.duration_ms"] == 7


# ------------------------------------------------------------------- metrics


def recorded() -> dict[str, list[Any]]:
    """Instrument name -> data points, from the in-memory reader."""
    data = METRICS.get_metrics_data()
    points: dict[str, list[Any]] = {}
    for resource in data.resource_metrics if data else []:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                points.setdefault(metric.name, []).extend(metric.data.data_points)
    return points


async def test_recall_counts_whether_it_matched_anything() -> None:
    """recall_match_rate (spec section 33) is this counter, sliced by `matched`."""
    await recall(
        _Session(),  # type: ignore[arg-type]
        PRINCIPAL,
        RecallQuery(task="extract text from a pdf"),
        model=HashingEmbedder(),
    )

    points = recorded()["recall_requests"]
    assert points, "recall recorded no data points"
    assert any(point.attributes.get("matched") is False for point in points)


async def test_queue_depth_is_sampled_when_it_is_read() -> None:
    """Queue depth was computed for /v1/ready and then thrown away."""
    assert await leases.depth(_Session()) == 0  # type: ignore[arg-type]

    points = recorded()["queue_depth"]
    assert [point.value for point in points] == [0]


def test_an_instrument_is_created_once_per_name() -> None:
    """The instruments are cached, so a hot path is not allocating one per call."""
    assert counter("executions_completed") is counter("executions_completed")


# ------------------------------------------------------- opt-in, and opt-out


@pytest.fixture
def otlp_endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    endpoint = "http://collector.invalid:4318"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    settings.cache_clear()
    yield endpoint
    settings.cache_clear()


def _ping_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "yes"}

    return app


def test_fastapi_is_not_instrumented_without_an_endpoint() -> None:
    """Unconfigured must cost nothing: no middleware, and the app still works."""
    settings.cache_clear()
    app = _ping_app()

    assert instrument_fastapi(app) is False

    SPANS.clear()
    assert TestClient(app).get("/ping").json() == {"pong": "yes"}
    assert not span_names()


def test_fastapi_is_instrumented_when_an_endpoint_is_configured(otlp_endpoint: str) -> None:
    app = _ping_app()

    assert instrument_fastapi(app) is True

    SPANS.clear()
    assert TestClient(app).get("/ping").json() == {"pong": "yes"}
    assert "GET /ping" in span_names()


def test_health_probes_are_excluded_from_tracing(otlp_endpoint: str) -> None:
    """A platform probes readiness forever; that volume would bury the requests
    anyone actually wants to look at."""
    app = FastAPI()

    @app.get("/v1/ready")
    async def ready() -> dict[str, bool]:
        return {"ready": True}

    instrument_fastapi(app)
    SPANS.clear()
    TestClient(app).get("/v1/ready")

    assert not span_names()


def test_the_api_app_still_builds_with_no_endpoint_configured() -> None:
    """The whole app, imported and constructed, with instrumentation off."""
    settings.cache_clear()
    from boobs_api.main import create_app

    assert create_app().title == "80085.ai"


def test_each_signal_gets_its_own_path() -> None:
    """OTEL_EXPORTER_OTLP_ENDPOINT is a base URL. Handing the base straight to
    both exporters posts traces and metrics to the same path, which no
    collector accepts."""
    assert _signal_endpoint("http://collector:4318", "traces") == "http://collector:4318/v1/traces"
    assert _signal_endpoint("http://collector:4318/", "metrics") == (
        "http://collector:4318/v1/metrics"
    )
    # Already signal-specific: left alone rather than doubled up.
    assert _signal_endpoint("http://collector:4318/v1/traces", "traces") == (
        "http://collector:4318/v1/traces"
    )

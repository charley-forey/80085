"""Embedding is CPU-bound ONNX inference. It must not run on the event loop.

A synchronous forward pass called straight from a coroutine holds the loop for
its whole duration, so one recall delays every other in-flight request on the
process -- /v1/health and /v1/ready included, which then answer late for a
server that is fine. The thread identity is the whole assertion: it is exact,
and it does not depend on timing.
"""

from __future__ import annotations

import threading

from boobs_domain.protocols import Principal, RecallQuery
from boobs_retrieval import pipeline
from boobs_retrieval.embedding import DIM, embed_in_thread


class ThreadRecordingEmbedder:
    """Records which thread ran the forward pass."""

    dim = DIM

    def __init__(self) -> None:
        self.thread: int | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.thread = threading.get_ident()
        return [[0.0] * DIM for _ in texts]


async def test_embed_in_thread_runs_the_model_off_the_loop() -> None:
    model = ThreadRecordingEmbedder()

    vectors = await embed_in_thread(model, ["convert a csv into json"])

    assert len(vectors) == 1
    assert model.thread is not None
    assert model.thread != threading.get_ident()


async def test_recall_does_not_embed_on_the_event_loop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The helper existing is not the point; the call site using it is.

    Both retrieval halves are stubbed empty so recall returns before it needs a
    database -- the embedding happens first, which is all this asserts about.
    """

    async def nothing(*args: object, **kwargs: object) -> dict[str, float]:
        return {}

    monkeypatch.setattr(pipeline, "_lexical", nothing)
    monkeypatch.setattr(pipeline, "_vector", nothing)
    model = ThreadRecordingEmbedder()

    matches = await pipeline.recall(
        db=None,  # type: ignore[arg-type]
        principal=Principal(organization_id="org_test", agent_id="agt_test"),
        query=RecallQuery(task="convert a csv into json"),
        model=model,
    )

    assert matches == []
    assert model.thread is not None
    assert model.thread != threading.get_ident()

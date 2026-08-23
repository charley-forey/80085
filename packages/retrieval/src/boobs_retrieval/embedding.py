"""Embeddings behind a protocol.

Default is a local ONNX model: no API key, no network at query time, and
deterministic in CI. Swapping in a hosted embedder means implementing
`Embedder` and changing one factory -- nothing else knows.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol, runtime_checkable

MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    dim = DIM

    def __init__(self, model: str = MODEL) -> None:
        from fastembed import TextEmbedding  # imported lazily: ~90MB model load

        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


class HashingEmbedder:
    """Deterministic stand-in for tests and offline environments.

    Not semantic -- it exists so retrieval code paths can be exercised without
    downloading a model. Never select this in production; lexical retrieval
    carries the query on its own if the real embedder is unavailable.
    """

    dim = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib
        import math

        vectors: list[list[float]] = []
        for text in texts:
            values = [0.0] * DIM
            for token in text.lower().split():
                index = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % DIM
                values[index] += 1.0
            norm = math.sqrt(sum(v * v for v in values)) or 1.0
            vectors.append([v / norm for v in values])
        return vectors


@lru_cache
def embedder() -> Embedder:
    """BOOBS_EMBEDDER=fastembed|hashing|auto (default auto).

    `auto` falls back to hashing when the model cannot load, and says so
    loudly: silent degradation of recall quality is the failure mode that
    would be hardest to notice from the outside.
    """
    import logging
    import os

    choice = os.environ.get("BOOBS_EMBEDDER", "auto")
    if choice == "hashing":
        return HashingEmbedder()
    try:
        return FastEmbedEmbedder()
    except Exception as exc:  # noqa: BLE001 - offline or model unavailable
        if choice == "fastembed":
            raise
        logging.getLogger(__name__).warning(
            "fastembed unavailable (%s); falling back to non-semantic HashingEmbedder. "
            "Vector recall is degraded; lexical recall is unaffected.",
            exc,
        )
        return HashingEmbedder()


def active_embedder() -> str:
    """Which embedder recall is really using: `fastembed` or `hashing`.

    `embedder()` is lru_cached, so one failed model load at startup degrades
    every recall for the life of the process and the only evidence is a single
    log line nobody reads. /v1/ready reports this so a degraded deployment is
    visible from outside the process instead.

    This forces the model load on first call, which is the point: an answer of
    "not loaded yet" would not tell an operator anything.
    """
    return "fastembed" if isinstance(embedder(), FastEmbedEmbedder) else "hashing"

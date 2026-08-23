"""Artifacts must be digest-pinned everywhere.

If a tag could be executed, every success rate the system reports would be a
statement about bytes that may no longer exist.
"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError as PydanticValidationError

from boobs_common.clock import now
from boobs_common.errors import ExecutionFailed
from boobs_domain.entities import Artifact
from boobs_domain.protocols import SandboxRequest
from boobs_execution import DockerOciRuntime, E2BRuntime
from boobs_schemas.api import ExecuteRequest

DIGEST = "sha256:" + "ab" * 32
PINNED = f"registry.example/80085/csv_to_json@{DIGEST}"


def test_pinned_reference_is_accepted() -> None:
    artifact = Artifact(id="art_1", reference=PINNED, digest=DIGEST, created_at=now())
    assert artifact.digest == DIGEST


@pytest.mark.parametrize(
    "reference",
    [
        "registry.example/80085/csv_to_json:latest",
        "registry.example/80085/csv_to_json",
        "registry.example/80085/csv_to_json@sha256:short",
    ],
)
def test_unpinned_references_are_refused(reference: str) -> None:
    with pytest.raises(PydanticValidationError):
        Artifact(id="art_1", reference=reference, digest=DIGEST, created_at=now())


def test_reference_digest_must_match_artifact_digest() -> None:
    other = "sha256:" + "cd" * 32
    with pytest.raises(PydanticValidationError):
        Artifact(id="art_1", reference=PINNED, digest=other, created_at=now())


@pytest.mark.parametrize("runtime", [DockerOciRuntime(), E2BRuntime()])
async def test_runtime_refuses_to_execute_an_unpinned_image(runtime: object) -> None:
    """Every runtime, not just the first one: a tag refused in one place and
    accepted in another is the same hole with extra steps."""
    request = SandboxRequest(
        execution_id="exec_1",
        image="python:3.13-slim",
        cpu=1,
        memory_mb=256,
        tmpfs_mb=256,
        timeout_seconds=5,
        pids=32,
        max_output_bytes=1024,
    )
    with pytest.raises(ExecutionFailed, match="unpinned"):
        await runtime.execute(request)  # type: ignore[attr-defined]


def test_execution_inputs_reject_path_traversal() -> None:
    blob = base64.b64encode(b"x").decode()
    for name in ("../escape.txt", "sub/dir.txt", ".hidden"):
        with pytest.raises(PydanticValidationError):
            ExecuteRequest(inputs={name: blob})


def test_execution_inputs_reject_non_base64() -> None:
    with pytest.raises(PydanticValidationError):
        ExecuteRequest(inputs={"data.csv": "not base64!!"})

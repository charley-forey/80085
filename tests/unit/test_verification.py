"""Verification is the line between a claim and evidence."""

from __future__ import annotations

import hashlib
import json

from boobs_domain.entities import VerificationSpec
from boobs_domain.enums import ExecutionStatus, VerificationLevel
from boobs_domain.protocols import SandboxResult
from boobs_verification.verifiers import RegistryVerifier

verifier = RegistryVerifier()


def result(**overrides: object) -> SandboxResult:
    base: dict[str, object] = {
        "status": ExecutionStatus.SUCCEEDED,
        "exit_code": 0,
        "duration_ms": 12,
        "output_files": {},
    }
    base.update(overrides)
    return SandboxResult(**base)  # type: ignore[arg-type]


async def test_failed_execution_never_verifies() -> None:
    outcome = await verifier.verify(
        result(status=ExecutionStatus.TIMEOUT, exit_code=None),
        VerificationSpec(verifier="exit_code"),
    )
    assert not outcome.passed
    assert outcome.level is VerificationLevel.UNVERIFIED


async def test_missing_output_is_a_failure_not_a_pass() -> None:
    outcome = await verifier.verify(
        result(), VerificationSpec(verifier="json_schema", config={"file": "output.json"})
    )
    assert not outcome.passed


async def test_schema_violation_fails() -> None:
    outcome = await verifier.verify(
        result(output_files={"output.json": json.dumps({"rows": 1}).encode()}),
        VerificationSpec(
            verifier="json_schema",
            config={"file": "output.json", "schema": {"type": "array"}},
        ),
    )
    assert not outcome.passed


async def test_schema_match_is_proven() -> None:
    outcome = await verifier.verify(
        result(output_files={"output.json": json.dumps([{"a": 1}]).encode()}),
        VerificationSpec(
            verifier="json_schema",
            config={"file": "output.json", "schema": {"type": "array"}},
        ),
    )
    assert outcome.passed
    assert outcome.level is VerificationLevel.PROVEN


async def test_sha256_verifier_catches_a_changed_byte() -> None:
    payload = b'{"ok": true}'
    spec = VerificationSpec(
        verifier="sha256",
        config={"file": "out.json", "sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert (await verifier.verify(result(output_files={"out.json": payload}), spec)).passed
    tampered = await verifier.verify(result(output_files={"out.json": payload + b" "}), spec)
    assert not tampered.passed


async def test_unknown_verifier_fails_closed() -> None:
    outcome = await verifier.verify(result(), VerificationSpec(verifier="vibes"))
    assert not outcome.passed
    assert "vibes" in str(outcome.detail)

"""Verifiers (spec section 18).

The product depends on one distinction: "the agent said it worked" versus
"the result was independently verified". Everything in this module produces
the second kind of claim, from evidence that can be recomputed later from the
stored execution.

Adding a verifier means writing one function and adding one line to REGISTRY.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from boobs_domain.entities import VerificationSpec
from boobs_domain.enums import ExecutionStatus, VerificationLevel
from boobs_domain.protocols import SandboxResult, VerificationResult

VerifierFn = Callable[[SandboxResult, dict[str, Any]], Awaitable[VerificationResult]]


def _fail(reason: str, **detail: Any) -> VerificationResult:
    return VerificationResult(
        passed=False, level=VerificationLevel.UNVERIFIED, detail={"reason": reason, **detail}
    )


def _pass(level: VerificationLevel, **detail: Any) -> VerificationResult:
    return VerificationResult(passed=True, level=level, detail=detail)


async def exit_code(result: SandboxResult, config: dict[str, Any]) -> VerificationResult:
    """The floor: the process ran to completion with the expected status.

    Passes at CLAIMED, not PROVEN. The exit code is chosen by the artifact,
    and the artifact is written by whoever wants the Experience recommended:
    `exit 0` is a claim the platform observed, not a result it checked. Only a
    verifier that inspects the *output* can say more than that.
    """
    expected = int(config.get("expected", 0))
    if result.status is not ExecutionStatus.SUCCEEDED and expected == 0:
        return _fail("execution did not succeed", status=result.status, exit_code=result.exit_code)
    if result.exit_code != expected:
        return _fail("unexpected exit code", expected=expected, actual=result.exit_code)
    return _pass(VerificationLevel.CLAIMED, exit_code=result.exit_code)


async def json_schema(result: SandboxResult, config: dict[str, Any]) -> VerificationResult:
    """The output file is present, is JSON, and matches a declared schema."""
    import jsonschema

    filename = config.get("file")
    if not filename:
        return _fail("json_schema verifier requires config.file")
    blob = result.output_files.get(filename)
    if blob is None:
        return _fail(
            "expected output file missing", file=filename, produced=sorted(result.output_files)
        )
    try:
        document = json.loads(blob)
    except json.JSONDecodeError as exc:
        return _fail("output is not valid JSON", file=filename, error=str(exc))

    schema = config.get("schema")
    if schema is None:
        # "It parsed" checks almost nothing about the answer, so it only
        # reaches CLAIMED. Declare a schema to earn PROVEN.
        return _pass(
            VerificationLevel.CLAIMED, file=filename, note="parsed as JSON; no schema declared"
        )
    try:
        jsonschema.validate(document, schema)
    except jsonschema.ValidationError as exc:
        return _fail("output does not match schema", file=filename, error=exc.message)
    return _pass(VerificationLevel.PROVEN, file=filename, schema_validated=True)


async def sha256(result: SandboxResult, config: dict[str, Any]) -> VerificationResult:
    """Byte-exact reproduction. The strongest claim available."""
    filename = config.get("file")
    expected = config.get("sha256")
    if not filename or not expected:
        return _fail("sha256 verifier requires config.file and config.sha256")
    blob = result.output_files.get(filename)
    if blob is None:
        return _fail(
            "expected output file missing", file=filename, produced=sorted(result.output_files)
        )
    actual = hashlib.sha256(blob).hexdigest()
    if actual != expected:
        return _fail("digest mismatch", file=filename, expected=expected, actual=actual)
    return _pass(VerificationLevel.PROVEN, file=filename, sha256=actual)


REGISTRY: dict[str, VerifierFn] = {
    "exit_code": exit_code,
    "json_schema": json_schema,
    "sha256": sha256,
}


class RegistryVerifier:
    """Implements the domain `Verifier` protocol by dispatching on name."""

    async def verify(
        self, result: SandboxResult, specification: VerificationSpec
    ) -> VerificationResult:
        verifier = REGISTRY.get(specification.verifier)
        if verifier is None:
            return _fail(
                "unknown verifier", verifier=specification.verifier, available=sorted(REGISTRY)
            )
        return await verifier(result, specification.config)

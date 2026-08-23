"""API keys (spec section 32): hashed at rest, scoped, revocable, auditable.

The plaintext key exists exactly once -- in the response to the call that
created it. Everything afterwards works from the SHA-256 hash. A key is
therefore unrecoverable, which is the point.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

PREFIX: Final = "sk_80085_"
_ENTROPY_BYTES: Final = 32


class Scope:
    """Coarse scopes. Fine-grained per-resource rules belong in PolicyEngine."""

    EXPERIENCES_READ: Final = "experiences:read"
    EXPERIENCES_WRITE: Final = "experiences:write"
    EXECUTIONS_RUN: Final = "executions:run"
    EXECUTIONS_VERIFY: Final = "executions:verify"
    ADMIN: Final = "admin"

    ALL: Final = frozenset({EXPERIENCES_READ, EXPERIENCES_WRITE, EXECUTIONS_RUN, EXECUTIONS_VERIFY})


def generate() -> tuple[str, str]:
    """Return (plaintext_key, key_hash). Store only the hash."""
    plaintext = PREFIX + secrets.token_urlsafe(_ENTROPY_BYTES)
    return plaintext, hash_key(plaintext)


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def matches(plaintext: str, key_hash: str) -> bool:
    """Constant-time compare, so a wrong key leaks no timing information."""
    return hmac.compare_digest(hash_key(plaintext), key_hash)


def looks_like_key(value: str) -> bool:
    return value.startswith(PREFIX) and len(value) > len(PREFIX) + 20

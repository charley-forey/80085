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
    # A worker leases jobs and reports raw results. It is deliberately NOT
    # granted the other scopes: it cannot read the registry or record anything.
    WORKER: Final = "worker:execute"
    ADMIN: Final = "admin"
    # Adding people to your own organization. Deliberately NOT part of ADMIN:
    # onboarding a colleague is a weekly act by whoever set the team up, and
    # quarantining a capability or granting an execution tier is not. Bundling
    # them meant a self-serve organization could never add a second person to
    # itself -- which is the one thing this product is for.
    PROVISION: Final = "agents:provision"

    # What an ordinary agent gets. Deliberately excludes WORKER and ADMIN.
    ALL: Final = frozenset({EXPERIENCES_READ, EXPERIENCES_WRITE, EXECUTIONS_RUN, EXECUTIONS_VERIFY})
    # What the first key of a self-serve organization gets: ordinary work, plus
    # the ability to bring colleagues into the organization it just created.
    FOUNDER: Final = ALL | frozenset({PROVISION})
    # Everything that may be granted. A scope outside this set is a typo, and
    # a typo that silently grants nothing is worse than a rejected request.
    KNOWN: Final = ALL | frozenset({WORKER, ADMIN, PROVISION})


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

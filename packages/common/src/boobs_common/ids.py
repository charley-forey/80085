"""Prefixed, sortable identifiers.

Prefixes make ids self-describing in logs and API responses. The body is a
uuid4 hex so ids carry no tenant information and cannot be enumerated.
"""

from __future__ import annotations

import uuid
from typing import Final

ORGANIZATION: Final = "org"
AGENT: Final = "agt"
API_KEY: Final = "key"
EXPERIENCE: Final = "exp"
VERSION: Final = "ver"
ARTIFACT: Final = "art"
EXECUTION: Final = "exec"
EVENT: Final = "evt"
VERIFICATION: Final = "vrf"
POLICY: Final = "pol"
RECALL_MISS: Final = "miss"
QUESTION: Final = "q"
ANSWER: Final = "ans"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def has_prefix(value: str, prefix: str) -> bool:
    return value.startswith(f"{prefix}_")

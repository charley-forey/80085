"""The MCP tool defaults must not drift from the HTTP API's.

MCP is the primary way an agent contributes, so a default that differs from
the API's is not a cosmetic inconsistency: `record_experience` defaulted to
`organization` while the API defaults to `public`, which meant every
contribution made through the main agent path was recorded private and no
other agent could ever recall it. A shared brain whose contributions default
to invisible is not shared.
"""

from __future__ import annotations

import inspect

from boobs_domain.enums import Visibility
from boobs_mcp.server import record_experience
from boobs_schemas.api import RecordExperienceRequest


def _mcp_default(parameter: str) -> object:
    return inspect.signature(record_experience).parameters[parameter].default


def test_mcp_visibility_default_matches_the_api() -> None:
    api_default = RecordExperienceRequest.model_fields["visibility"].default
    assert api_default is Visibility.PUBLIC
    assert _mcp_default("visibility") == api_default.value


def test_mcp_visibility_default_is_a_real_visibility() -> None:
    """A typo here would be accepted by the tool and rejected by the API."""
    assert Visibility(_mcp_default("visibility")) is Visibility.PUBLIC

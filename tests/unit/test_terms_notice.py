"""The terms are only protective if a caller is actually told about them.

Recall needs no key, so there is no signup screen to put a notice on. What is
left is the machine-readable surface: the OpenAPI document, and a Link header
on every response. Both are asserted here because both are one careless edit
away from disappearing silently, and a term nobody was shown is a term nobody
is bound by.

The other half -- that a breach is *observable* -- is the 429 mapping. A limit
that refuses without recording anything leaves no pattern to point at later.
"""

from __future__ import annotations

from boobs_api.limits import RateLimited
from boobs_api.main import STATUS_FOR, create_app


def test_openapi_names_both_instruments() -> None:
    """Code and corpus are licensed separately; the schema has to say so."""
    info = create_app().openapi()["info"]

    assert info["license"]["url"].endswith("/LICENSE")
    assert "Elastic License 2.0" in info["license"]["name"]
    # The corpus terms are the ones that actually protect the asset, so they
    # are not allowed to be the field that quietly goes missing.
    assert info["termsOfService"].endswith("/TERMS.md")


def test_rate_limit_is_reported_as_429() -> None:
    """Not 500. A 429 is the status the logging branch keys off."""
    assert STATUS_FOR[RateLimited] == 429


def test_mcp_handshake_carries_both_the_directive_and_the_terms() -> None:
    """The handshake is the whole onboarding, and the only notice MCP gets.

    The site no longer tells anyone to paste a system prompt, because
    `initialize` delivers the recall directive on connect. Losing either half
    of this string breaks something that has no other home: the install story,
    or the only moment an MCP caller is shown what binds it.
    """
    from boobs_mcp.server import mcp

    instructions = mcp.instructions or ""

    assert "recall_experience" in instructions
    assert "TERMS.md" in instructions
    assert "bulk-extract" in instructions


def test_every_response_advertises_the_terms() -> None:
    """The Link header is the only notice an HTTP-only agent ever sees."""
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        link = client.get("/health").headers["Link"]

    assert 'rel="license"' in link
    assert 'rel="terms-of-service"' in link
    assert "/TERMS.md" in link

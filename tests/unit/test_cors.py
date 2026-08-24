"""The browser is a client too.

/key and the homepage mint a key with `fetch` from 80085.ai to api.80085.ai.
A cross-origin POST with no CORS header is sent by the browser and then hidden
from the page, so the key was minted and the visitor saw "Failed to fetch".
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from boobs_api.main import create_app


def test_a_page_on_the_apex_may_read_the_mint_response() -> None:
    with TestClient(create_app()) as client:
        preflight = client.options(
            "/v1/keys",
            headers={
                "Origin": "https://80085.ai",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "*"
    assert "POST" in preflight.headers["access-control-allow-methods"]

"""The apex and the API serve the same site. Nothing checked that they agreed.

`apps/web/vercel.json` and `_representation` in `apps/api` are two hand-written
implementations of one negotiation table, and `DEPLOY.md` says outright that
they mirror each other. They did not: `/recall`, `/boobs` and `/58008` were
rewritten on Vercel and 404 on `api.80085.ai`, live, for as long as anyone had
been looking.

It stayed invisible because DNS points the apex at Vercel, so the broken half
is the one nobody visits -- while `DEPLOY.md` calls serving from the API the
primary path, and `terminal.js` fetches a *relative* `/recall?q=`, which breaks
the moment that path is used.

Two implementations of one rule need a test that reads both. This is it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boobs_api.main import _ALIASES, _NEGOTIABLE, create_app

VERCEL = Path(__file__).resolve().parents[2] / "apps" / "web" / "vercel.json"


def vercel_sources() -> set[str]:
    """Every path Vercel rewrites, normalised the way _NEGOTIABLE stores them."""
    config = json.loads(VERCEL.read_text(encoding="utf-8"))
    paths: set[str] = set()
    for rule in config.get("rewrites", []):
        source = str(rule.get("source", ""))
        # Vercel sources can carry regex groups and :params; the negotiated
        # ones are plain paths, and those are the only ones this compares.
        if any(character in source for character in "(:*?[") or not source.startswith("/"):
            continue
        paths.add(source.rstrip("/") or "/")
    return paths


@pytest.mark.skipif(not VERCEL.is_file(), reason="apps/web/vercel.json is not in this checkout")
def test_every_path_vercel_rewrites_is_answered_by_the_api_too() -> None:
    # A path is answered if negotiation rewrites it *or* the app already
    # routes it -- /openapi.json and /docs are FastAPI's own, and asking
    # _NEGOTIABLE about them would be looking in the wrong place. Reading the
    # real route table means a future route counts automatically.
    routed = {
        str(getattr(route, "path", "")).rstrip("/") or "/"
        for route in create_app().routes
        if getattr(route, "path", None)
    }
    answered = set(_NEGOTIABLE) | set(_ALIASES) | routed
    missing = sorted(vercel_sources() - answered)
    assert not missing, (
        "these paths are rewritten on the apex and 404 on the API host, so the "
        "site answers differently depending which host serves it: " + ", ".join(missing)
    )


def test_the_joke_urls_survive_because_people_share_them() -> None:
    """Regression: these were the 404s, and they are the links people send."""
    for path in ("/boobs", "/58008"):
        assert path in _NEGOTIABLE, f"{path} stopped being served"


def test_recall_is_an_alias_not_a_page() -> None:
    """It proxies a real route. Rendering a page there would answer 200 with
    the wrong thing, which is worse than the 404 it replaced."""
    assert _ALIASES["/recall"] == "/v1/recall"
    assert "/recall" not in _NEGOTIABLE

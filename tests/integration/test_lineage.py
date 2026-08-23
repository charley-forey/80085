"""Lineage resolution, over HTTP and against a real database.

The claim that matters is a claim about a `WHERE` clause: an edge naming
another organization's *private* Experience must resolve to exactly what an
edge naming an id that was never recorded resolves to. Nothing validates a
lineage id at write time, so writing that edge costs an attacker one request --
and if resolution answered the two cases differently, this endpoint would tell
anyone who can record whether an arbitrary id exists, and what its goal says.

A mock cannot prove that. `visibility_clause` is SQL.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from tests.helpers import auth, bootstrap

pytestmark = [pytest.mark.integration]

NEVER_RECORDED = "exp_" + "0" * 32


def _digest() -> str:
    return "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex


async def _record(
    api: httpx.AsyncClient, key: str, caller: str, statement: str, **overrides: Any
) -> str:
    """Record from a named address, so each test has its own write budget."""
    body: dict[str, Any] = {
        "goal": {"statement": statement, "intent": "lineage_probe", "tags": []},
        "artifact": {"type": "oci", "reference": f"registry.test/80085/lineage@{_digest()}"},
        "command": ["python", "/app/main.py"],
        "environment": {"os": "linux", "architecture": "amd64", "runtime": "python"},
        "visibility": "public",
    }
    body.update(overrides)
    response = await api.post(
        "/v1/experiences", headers={**auth(key), "x-forwarded-for": caller}, json=body
    )
    assert response.status_code == 201, response.text
    return str(response.json()["experience_id"])


async def _lineage(api: httpx.AsyncClient, key: str, experience_id: str, **params: int) -> Any:
    response = await api.get(
        f"/v1/experiences/{experience_id}/lineage", headers=auth(key), params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------- tenancy


async def test_a_private_target_answers_exactly_as_a_missing_one_does(
    api: httpx.AsyncClient,
) -> None:
    """The leak. One org keeps an Experience private; another names its id.

    The private id is not guessable, but it does not have to be guessed: it is
    handed to its owner in plain text at record, it travels in logs and in
    prompts, and the only question left is whether this endpoint will confirm
    it. It will not -- and it will not confirm the absence of a made-up id
    either, which is the same fact stated from the other side.
    """
    victim = await bootstrap(api, "lineage-victim", "victim")
    secret = await _record(
        api,
        victim,
        "198.51.100.60",
        "the private thing nobody else may know exists",
        visibility="private",
    )

    attacker = await bootstrap(api, "lineage-attacker", "attacker")
    probe = await _record(
        api,
        attacker,
        "198.51.100.61",
        "claims to improve something it cannot see",
        lineage={"improves": secret, "forked_from": NEVER_RECORDED},
    )

    nodes = (await _lineage(api, attacker, probe))["nodes"]
    assert len(nodes) == 2
    by_relation = {node["relation"]: node for node in nodes}

    private_edge = by_relation["improves"]
    missing_edge = by_relation["forked_from"]
    assert private_edge["experience_id"] == secret
    assert missing_edge["experience_id"] == NEVER_RECORDED
    # Identical in every respect except which id was named and by which
    # relation -- both of which the attacker wrote themselves.
    assert {k: v for k, v in private_edge.items() if k not in {"relation", "experience_id"}} == {
        k: v for k, v in missing_edge.items() if k not in {"relation", "experience_id"}
    }
    assert private_edge["resolved"] is False
    assert "goal" not in private_edge, "the private goal statement came back"
    assert "nobody else may know" not in str(nodes)


async def test_the_owner_of_the_private_experience_still_resolves_it(
    api: httpx.AsyncClient,
) -> None:
    """The same edge, from the one caller entitled to it, is not hidden.

    Otherwise "identical answers" would be satisfied by resolving nothing.
    """
    owner = await bootstrap(api, "lineage-owner", "owner")
    secret = await _record(
        api, owner, "198.51.100.62", "the private thing, seen by its owner", visibility="private"
    )
    theirs = await _record(
        api, owner, "198.51.100.62", "builds on our own private work", lineage={"improves": secret}
    )

    (node,) = (await _lineage(api, owner, theirs))["nodes"]
    assert node["resolved"] is True
    assert node["experience_id"] == secret
    assert node["goal"] == "the private thing, seen by its owner"


async def test_a_public_target_resolves_into_something_actionable(
    api: httpx.AsyncClient,
) -> None:
    """An id alone is not a reason to run or not run anything."""
    author = await bootstrap(api, "lineage-public", "author")
    original = await _record(api, author, "198.51.100.63", "the original approach")
    better = await _record(
        api, author, "198.51.100.63", "a faster approach", lineage={"supersedes": original}
    )

    reader = await bootstrap(api, "lineage-reader", "reader")
    (node,) = (await _lineage(api, reader, better))["nodes"]
    assert node["resolved"] is True
    assert node["relation"] == "supersedes"
    assert node["goal"] == "the original approach"
    assert node["latest_version"] == 1
    assert node["status"] == "candidate"


# --------------------------------------------------------------- termination


async def test_a_cycle_between_two_experiences_terminates(api: httpx.AsyncClient) -> None:
    """`A supersedes B supersedes A` is writable today: append-only versions
    mean the second edge can always be added after the first id exists."""
    author = await bootstrap(api, "lineage-cycle", "author")
    first = await _record(api, author, "198.51.100.64", "the first half of a cycle")
    second = await _record(
        api, author, "198.51.100.64", "the second half", lineage={"supersedes": first}
    )
    # A new version of the first, pointing back. The old version keeps its own
    # lineage forever; traversal reads the latest, which is now a cycle.
    await _record(
        api,
        author,
        "198.51.100.64",
        "the first half of a cycle",
        experience_id=first,
        lineage={"supersedes": second},
    )

    answer = await _lineage(api, author, first, depth=5)
    assert [node["experience_id"] for node in answer["nodes"]] == [second]
    assert answer["truncated"] is False


# ---------------------------------------------------------- what is surfaced


async def test_a_caller_can_read_back_the_lineage_they_recorded(
    api: httpx.AsyncClient,
) -> None:
    """Which nothing could do at all: six relations written since the first
    migration and no response model that carried them."""
    author = await bootstrap(api, "lineage-readback", "author")
    parent = await _record(api, author, "198.51.100.65", "the parent")
    child = await _record(
        api, author, "198.51.100.65", "the child", lineage={"forked_from": parent}
    )

    body = (await api.get(f"/v1/experiences/{child}", headers=auth(author))).json()
    # Sparse: the five relations that were not set cost the reader nothing.
    assert body["lineage"] == {"forked_from": parent}


async def test_lineage_of_something_you_cannot_see_is_not_traversable(
    api: httpx.AsyncClient,
) -> None:
    """The root goes through the ordinary read rules, not around them."""
    victim = await bootstrap(api, "lineage-root-victim", "victim")
    secret = await _record(
        api, victim, "198.51.100.66", "private, and not a traversal root", visibility="private"
    )

    stranger = await bootstrap(api, "lineage-root-stranger", "stranger")
    refused = await api.get(f"/v1/experiences/{secret}/lineage", headers=auth(stranger))
    assert refused.status_code == 403, refused.text

    missing = await api.get(f"/v1/experiences/{NEVER_RECORDED}/lineage", headers=auth(stranger))
    assert missing.status_code == 404, missing.text

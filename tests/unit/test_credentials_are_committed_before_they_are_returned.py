"""A credential must be committed before the caller is told what it is.

`get_db` commits in its dependency teardown, and FastAPI runs that *after* the
response has been sent. So an endpoint that only flushed handed out an API key
whose row no other connection could see yet: the caller used it immediately --
which is the entire self-serve onboarding path, because the key is the account
-- and got `401 unknown api key`. Intermittently, which is worse than always.

These are ordering tests, not timing tests. The fake session records what the
handler did and in which order; the property is that the last thing before the
credential goes out is a commit. Under the old code the log ended with a
flush, so this fails on it deterministically rather than one time in twenty.

tests/integration/test_mint_then_use.py asserts the same thing the way a
caller experiences it: mint, then immediately authenticate, repeatedly.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from boobs_api import routes
from boobs_common.clock import now
from boobs_common.errors import NotFound
from boobs_domain.protocols import Principal
from boobs_schemas.api import ArtifactIn, BootstrapRequest, GoalIn, RecordExperienceRequest
from boobs_schemas.tables import ApiKey
from boobs_security.keys import Scope

ORG = "org_minting"


class Session:
    """Enough AsyncSession to run a handler, plus the order it did things in."""

    def __init__(self, *rows: Any) -> None:
        self._rows = list(rows)
        self.log: list[str] = []

    async def execute(self, _: Any, params: Any = None) -> Any:
        # The rate limiter's counter comes back as a plain number; every other
        # statement is a row lookup.
        self.log.append("query")
        row = self._rows.pop(0) if self._rows else 1
        return SimpleNamespace(scalar_one=lambda: row, scalar_one_or_none=lambda: row)

    def add(self, row: Any) -> None:
        self.log.append(f"add:{type(row).__name__}")

    async def flush(self) -> None:
        self.log.append("flush")

    async def commit(self) -> None:
        self.log.append("commit")

    async def rollback(self) -> None:
        self.log.append("rollback")


def a_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/keys",
            "query_string": b"",
            "headers": [],
            "client": ("198.51.100.4", 5000),
        }
    )


def assert_committed_before_returning(log: list[str]) -> None:
    assert "flush" in log or "query" in log, f"the handler wrote nothing: {log}"
    assert log[-1] == "commit", f"the credential was handed over uncommitted: {log}"


async def test_minting_commits_before_it_hands_over_the_key() -> None:
    db = Session()
    minted = await routes.mint_key(http=a_request(), db=db, label="tester")  # type: ignore[arg-type]

    assert minted["api_key"].startswith("sk_80085_")
    assert_committed_before_returning(db.log)
    # And the key row itself is in the committed transaction, not a later one.
    assert "add:ApiKey" in db.log
    assert db.log.index("add:ApiKey") < len(db.log) - 1


async def test_the_minted_key_can_be_revoked_later() -> None:
    """A self-serve caller has no account to look anything up in, so the id is
    only ever available in this one response."""
    minted = await routes.mint_key(http=a_request(), db=Session(), label=None)  # type: ignore[arg-type]
    assert minted["key_id"].startswith("key_")


async def test_bootstrap_commits_before_it_hands_over_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It mints too, so it had the same race for the same reason."""
    monkeypatch.setenv("BOOBS_BOOTSTRAP_TOKEN", "token")
    db = Session()
    minted = await routes.bootstrap(
        request=BootstrapRequest(organization="acme", agent="a", token="token"),
        db=db,  # type: ignore[arg-type]
    )

    assert minted["api_key"].startswith("sk_80085_")
    assert minted["key_id"].startswith("key_")
    assert_committed_before_returning(db.log)


async def test_revocation_commits_before_it_reports_success() -> None:
    """The mirror image: a caller told a key is dead must not find it alive."""
    key = ApiKey(
        id="key_revoked",
        organization_id=ORG,
        agent_id="agt_minting",
        name="leaked",
        key_hash="x" * 64,
        scopes=[Scope.EXPERIENCES_READ],
        created_at=now(),
    )
    db = Session(key)
    answer = await routes.revoke_key(
        key_id=key.id,
        db=db,  # type: ignore[arg-type]
        principal=Principal(
            organization_id=ORG, agent_id="agt_minting", scopes=frozenset({Scope.EXPERIENCES_READ})
        ),
    )

    assert answer["revoked_at"] is not None
    assert_committed_before_returning(db.log)


async def test_revoking_a_key_that_does_not_exist_is_not_found() -> None:
    with pytest.raises(NotFound):
        await routes.revoke_key(
            key_id="key_nope",
            db=Session(None),  # type: ignore[arg-type]
            principal=Principal(organization_id=ORG, agent_id="agt_minting"),
        )


async def test_recording_commits_before_it_returns_the_experience_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An id is a promise that the row is there, exactly like a credential.

    Fixing the credential race made this one visible rather than causing it:
    tests that used to die on `401 unknown api key` got further, recorded an
    Experience, used the id it returned on the next request, and were told the
    Experience did not exist. Record, execute, recall and cross-tenant reads
    all failed that way, which reads as lost data and is really one commit
    arriving after one response.
    """
    db = Session()

    class Experiences:
        def __init__(self, _db: Any) -> None: ...

        async def create(self, _principal: Any, _request: Any) -> Any:
            db.add(SimpleNamespace())
            await db.flush()
            return SimpleNamespace(id="exp_1"), SimpleNamespace(id="ver_1", artifact_id="art_1")

    class Artifacts:
        def __init__(self, _db: Any) -> None: ...

        async def resolve(self, _artifact_id: str) -> Any:
            return SimpleNamespace(digest="sha256:" + "a" * 64)

    monkeypatch.setattr(routes, "ExperienceRepository", Experiences)
    monkeypatch.setattr(routes, "ArtifactRepository", Artifacts)
    monkeypatch.setattr(routes, "_experience_response", lambda *_a, **_k: "recorded")

    answer = await routes.record_experience(
        request=RecordExperienceRequest(
            goal=GoalIn(statement="convert csv to json", intent="csv_to_json"),
            artifact=ArtifactIn(type="oci", reference="repo/thing@sha256:" + "b" * 64),
            command=["python", "main.py"],
        ),
        http=a_request(),
        db=db,  # type: ignore[arg-type]
        principal=Principal(organization_id=ORG, agent_id="agt_minting"),
    )

    assert answer == "recorded"
    assert_committed_before_returning(db.log)

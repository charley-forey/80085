"""What it takes to withdraw a capability, and to get one back.

`quarantined` was a status two places read and nothing wrote (DECISIONS 56).
These pin the arithmetic of the automatic writer and the refusals of the manual
one; that the whole thing works against real rows -- a failing capability
dropping out of recall, and a recovered one coming back -- is asserted in
`tests/integration/test_quarantine.py`.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request

from boobs_api import routes
from boobs_common.clock import now
from boobs_common.errors import Forbidden, NotFound
from boobs_domain.enums import ExperienceStatus
from boobs_domain.protocols import Principal
from boobs_reputation import evidence
from boobs_retrieval.ranking import STALE_AFTER_DAYS
from boobs_schemas.api import QuarantineRequest
from boobs_security.keys import Scope

# --------------------------------------------------------------- the arithmetic


def _window(*outcomes: bool, age_days: float = 0.0) -> list[tuple[Any, bool]]:
    """A run of outcomes, oldest first, finishing `age_days` ago."""
    moment = now() - timedelta(days=age_days)
    return [(moment - timedelta(minutes=len(outcomes) - i), ok) for i, ok in enumerate(outcomes)]


def test_a_capability_whose_recent_runs_fail_is_rotten() -> None:
    assert evidence.rotten(_window(*[False] * 10))


def test_a_long_history_of_success_does_not_save_a_broken_capability() -> None:
    """The window is the point. An Experience with nine hundred successes and
    its last twenty runs all failing is broken *now*, and its lifetime success
    rate is the number that says otherwise."""
    assert evidence.rotten(_window(*[False] * evidence.QUARANTINE_WINDOW))


def test_two_failures_are_not_rot() -> None:
    """Below the floor there is no trend, only noise -- and a capability
    withdrawn on two bad runs is a corpus that empties itself."""
    assert not evidence.rotten(_window(False, False))


def test_a_minority_of_failures_is_not_rot() -> None:
    assert not evidence.rotten(_window(*([False] * 5 + [True] * 5)))


def test_failures_nobody_can_reproduce_do_not_quarantine() -> None:
    """`ranking.recency_score` already scores two-year-old evidence at nothing.
    Withdrawing something from recall on it would be acting on a claim that
    cannot be checked, which is the opposite of what this corpus sells."""
    assert not evidence.rotten(_window(*[False] * 10, age_days=STALE_AFTER_DAYS + 1))
    assert evidence.rotten(_window(*[False] * 10, age_days=1))


def test_recovery_needs_a_clear_run_not_a_lucky_one() -> None:
    """One success after nineteen failures must not release anything."""
    assert not evidence.recovered(_window(*([False] * 19 + [True])))
    assert evidence.recovered(_window(*[True] * 10))


def test_entering_and_leaving_do_not_meet() -> None:
    """The hysteresis gap, asserted as a property rather than as two numbers.

    Every window in the gap is neither rot nor recovery, so a capability
    sitting on the threshold stays where it is instead of flapping in and out
    of recall on each run -- which is worse than either state, because it makes
    the corpus's answer depend on the minute you asked.
    """
    size = evidence.QUARANTINE_WINDOW
    undecided = 0
    for failures in range(size + 1):
        window = _window(*([False] * failures + [True] * (size - failures)))
        rotten, recovered = evidence.rotten(window), evidence.recovered(window)
        assert not (rotten and recovered), f"{failures}/{size} is both rot and recovery"
        undecided += not rotten and not recovered
    assert undecided >= size // 2, "the gap is too narrow to stop a capability thrashing"


def test_it_takes_most_of_the_window_to_change_its_mind() -> None:
    """Concretely: a quarantined version has to replace twelve of its last
    twenty outcomes before anything moves, so no single run can flip it."""
    size = evidence.QUARANTINE_WINDOW
    enters = min(f for f in range(size + 1) if evidence.rotten(_window(*_mix(f, size))))
    leaves = max(f for f in range(size + 1) if evidence.recovered(_window(*_mix(f, size))))
    assert enters - leaves >= size // 2


def _mix(failures: int, size: int) -> list[bool]:
    return [False] * failures + [True] * (size - failures)


# ------------------------------------------------------------ the manual writer


class Session:
    """Answers `execute` from a prepared queue, in the order the handler asks."""

    def __init__(self, *results: Any) -> None:
        self._results = list(results)

    async def execute(self, *_: Any, **__: Any) -> Any:
        value = self._results.pop(0)
        return SimpleNamespace(scalar_one=lambda: value, scalar_one_or_none=lambda: value)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "client": ("10.0.0.9", 5000),
            "headers": [],
        }
    )


def _principal(*scopes: str) -> Principal:
    return Principal(organization_id="org_caller", agent_id="agt_caller", scopes=frozenset(scopes))


def _experience(status: str = ExperienceStatus.VERIFIED) -> Any:
    return SimpleNamespace(
        id="exp_target",
        organization_id="org_someone_else",
        status=status,
        quarantine=None,
        updated_at=now(),
    )


@pytest.fixture(autouse=True)
def _no_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The window is asserted over the router in test_open_access.py."""

    async def check(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(routes.limits.QUARANTINE, "check", check)


async def test_an_ordinary_key_cannot_withdraw_a_capability() -> None:
    """This is a denial-of-service primitive pointed at whichever experience id
    you can name, and ids are handed out by recall to anyone who asks."""
    experience = _experience()
    with pytest.raises(Forbidden):
        await routes.set_quarantine(
            experience_id="exp_target",
            request=QuarantineRequest(quarantined=True, reason="I do not like it"),
            http=_request(),
            db=Session(experience),  # type: ignore[arg-type]
            principal=_principal(
                Scope.EXPERIENCES_READ, Scope.EXPERIENCES_WRITE, Scope.EXECUTIONS_RUN
            ),
        )
    assert experience.status == ExperienceStatus.VERIFIED


async def test_a_worker_key_cannot_either() -> None:
    with pytest.raises(Forbidden):
        await routes.set_quarantine(
            experience_id="exp_target",
            request=QuarantineRequest(quarantined=True, reason="worker says no"),
            http=_request(),
            db=Session(_experience()),  # type: ignore[arg-type]
            principal=_principal(Scope.WORKER),
        )


async def test_quarantining_names_an_experience_that_has_to_exist() -> None:
    with pytest.raises(NotFound):
        await routes.set_quarantine(
            experience_id="exp_typo",
            request=QuarantineRequest(quarantined=True, reason="a typo, not a capability"),
            http=_request(),
            db=Session(None),  # type: ignore[arg-type]
            principal=_principal(Scope.ADMIN),
        )


async def test_an_admin_quarantine_records_who_and_why() -> None:
    """The row is the audit trail, so the reason lives on it and not in a log.

    Marked `manual`, which is load-bearing: `recompute` releases its own
    quarantines when the runs recover, and must never release this one.
    """
    experience = _experience()
    answer = await routes.set_quarantine(
        experience_id="exp_target",
        request=QuarantineRequest(quarantined=True, reason="ships a credential in the image"),
        http=_request(),
        db=Session(experience),  # type: ignore[arg-type]
        principal=_principal(Scope.ADMIN),
    )
    assert experience.status == ExperienceStatus.QUARANTINED
    assert experience.quarantine["reason"] == "ships a credential in the image"
    assert experience.quarantine["by"] == "agt_caller"
    assert experience.quarantine["manual"] is True
    assert answer.status == ExperienceStatus.QUARANTINED
    assert answer.quarantine is not None


async def test_releasing_lands_on_candidate_and_not_on_verified() -> None:
    """Corroboration is re-earned through `recompute` like anything else. A
    status restored by hand is exactly the self-attestation decision 41
    exists to prevent."""
    experience = _experience(ExperienceStatus.QUARANTINED)
    experience.quarantine = {"reason": "was wrong", "manual": True}
    answer = await routes.set_quarantine(
        experience_id="exp_target",
        request=QuarantineRequest(quarantined=False, reason="the image was rebuilt clean"),
        http=_request(),
        db=Session(experience),  # type: ignore[arg-type]
        principal=_principal(Scope.ADMIN),
    )
    assert experience.status == ExperienceStatus.CANDIDATE
    assert experience.quarantine is None
    assert answer.status == ExperienceStatus.CANDIDATE
    assert answer.quarantine is None


def test_a_withdrawal_needs_a_stated_reason() -> None:
    """Taking a capability away from every agent asking for it, with no cause
    recorded, is indistinguishable from a leaked admin key."""
    with pytest.raises(ValueError):
        QuarantineRequest(quarantined=True, reason="nope")


def test_the_action_is_admin_only_and_mutating() -> None:
    """Both halves matter: `admin` is the scope, and being a MUTATING_ACTION is
    why the route passes no resource -- an ownership a cross-tenant admin
    action cannot have (DECISIONS 39, 53)."""
    from boobs_security.policy import ACTION_SCOPES, MUTATING_ACTIONS

    assert ACTION_SCOPES["admin.quarantine"] == Scope.ADMIN
    assert "admin.quarantine" in MUTATING_ACTIONS

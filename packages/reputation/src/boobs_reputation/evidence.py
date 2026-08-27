"""Evidence and reputation (spec sections 19, 22 and 24).

Not a rating system. The only question is "will this probably work for me",
so every number here is derived from immutable execution and verification
rows and can be rebuilt from scratch at any time.

A run counts as *successful* only if the sandbox succeeded AND a verifier
passed. That is the whole distinction the product sells: an agent's claim is
not evidence.

A run the worker replayed from its cache counts as neither, because it is not
an observation at all -- it is the previous run being read back.

**Derived, and now folded rather than re-scanned.** DECISIONS 11 said evidence
is recomputed and never incremented, because a counter drifts and a full scan
cannot. It was also O(history) on the request path, twice per run, forever --
so a capability was charged more for evidence the more evidence it already
had. Decision 57 keeps the invariant and drops the scan: `_rebuild` is still
the definition, still reads only immutable rows, and still produces every
number from nothing; `_extend` folds *only what has happened since the
checkpoint* on to the last answer, which is exact precisely because the rows
it already read can never change. Anything that could invalidate what was
already folded -- a run that was counted and is only now being verified --
falls back to `_rebuild`, and the scheduler's `evidence` job rebuilds on a
clock regardless. The checkpoint is a cache of a pure function of immutable
rows: delete the column and every number comes back identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common.clock import now
from boobs_common.config import settings
from boobs_domain.enums import ExecutionStatus, ExperienceStatus, VerificationLevel
from boobs_retrieval.ranking import VERIFICATION_STRENGTH, confidence_score, recency_score
from boobs_schemas.tables import (
    Execution,
    ExecutionStat,
    Experience,
    ExperienceVersion,
    Organization,
    Verification,
)

TERMINAL = (
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMEOUT,
    ExecutionStatus.REJECTED,
)

# When a run finished. `completed_at` is set by every path that makes a row
# terminal, but the column is nullable, and a cursor that skipped a null would
# silently lose the row -- so the cursor is defined over this, not the column.
FINISHED_AT = func.coalesce(Execution.completed_at, Execution.created_at)

# How many of the most recent runs the staleness policy looks at, and the floor
# below which a run of failures is noise rather than rot. Twenty and five are
# deliberately small: an Experience that has broken should stop being
# recommended within an afternoon, not within a quarter.
QUARANTINE_WINDOW = 20
QUARANTINE_MIN_RUNS = 5

# Hysteresis. Entering costs 80% of the window failing; leaving costs 20% or
# fewer. The gap is what stops a capability sitting on a threshold flapping in
# and out of recall on every run -- which is worse than either state, because
# it makes the corpus's answer depend on the minute you asked. With a
# twenty-run window, a quarantined version has to replace twelve of its last
# twenty outcomes before anything moves.
QUARANTINE_AT = 0.8
RELEASE_AT = 0.2

# The most recent successful durations kept for the percentiles. Latency is the
# one number where the whole history is actively misleading: a p95 over runs
# from two years ago describes hardware nobody is using. Bounded here so the
# checkpoint cannot grow with the run count.
DURATION_SAMPLES = 200

# ponytail: the checkpoint remembers the ids that finished in its cursor's
# exact instant, so a `>=` rescan cannot count them twice. Real traffic puts
# one row in that instant; a bulk backfill can put thousands, and rather than
# store them the checkpoint is declared unusable and the next call rebuilds.
# Ceiling: a version whose runs all share one timestamp never folds. Upgrade
# path is a monotonic sequence on `executions` to cursor over instead of a clock.
BOUNDARY_LIMIT = 64


async def independent_organizations(db: AsyncSession, organizations: set[str]) -> int:
    """How many distinct *parties* ran this, not how many organization rows.

    Organizations are free, so the operator of a registry can seed a corpus as
    one organization, execute it as a second, and watch its own artifacts
    promote themselves to `use` -- which is the Sybil pattern the gate exists
    to stop, performed by the one actor the gate never thought to check.

    `EVIDENCE_FIRST_PARTY_ORGANIZATIONS` names the operator's own
    organizations, and every one of them counts once between them. The rest
    count individually, because nothing is known about them and nothing is
    claimed: this buys independence from the operator, not identity.

    Counted here rather than recorded at execution time on purpose. The set of
    organization ids in the checkpoint is immutable history; which of them are
    the operator's is a fact about today. Adding a name to the list re-derives
    every score correctly on the next fold, and removing one puts them back.
    """
    first_party = settings().evidence.first_party()
    if not first_party or not organizations:
        return len(organizations)

    # A trailing `*` matches by prefix, because some of our own organizations
    # are named per run -- `smoke-producer-<run id>` is first-party every time
    # and never twice by the same name. A list that cannot express them would
    # be a list that quietly leaves the hole it was written to close.
    exact = {name for name in first_party if not name.endswith("*")}
    match: list[ColumnElement[bool]] = [
        Organization.name.startswith(name[:-1]) for name in first_party if name.endswith("*")
    ]
    if exact:
        match.append(Organization.name.in_(exact))

    ours = set(
        (
            await db.execute(
                select(Organization.id).where(Organization.id.in_(organizations), or_(*match))
            )
        )
        .scalars()
        .all()
    )
    return collapse(organizations, ours)


def collapse(organizations: set[str], first_party: set[str]) -> int:
    """Every first-party organization counts once between them, together."""
    ours = organizations & first_party
    return len(organizations - ours) + (1 if ours else 0)


def corroborated(distinct_organizations: int) -> bool:
    """Has anyone other than the author proven this?

    Minting an organization costs nothing, so this is not identity and does not
    pretend to be. What it does buy is that manufacturing a VERIFIED Experience
    stops being a side effect of recording one: an artifact that exits 0 on
    demand no longer promotes itself the first time its author runs it.
    """
    return distinct_organizations >= settings().evidence.min_promotion_organizations


@dataclass
class _Evidence:
    """Everything the numbers are made of, and where the reading got to.

    Folded forward by `_extend`, produced from nothing by `_rebuild`. The two
    must agree exactly, which is what the integration test asserts against a
    real history rather than against a fixture.
    """

    successful: int = 0
    failed: int = 0
    organizations: set[str] = field(default_factory=set)
    durations: list[int] = field(default_factory=list)
    failure_modes: dict[str, int] = field(default_factory=dict)
    # (finished_at, did it work) for the most recent QUARANTINE_WINDOW runs,
    # oldest first. The staleness policy reads this and nothing else.
    recent: list[tuple[datetime, bool]] = field(default_factory=list)
    level: VerificationLevel = VerificationLevel.UNVERIFIED
    last_verified: datetime | None = None
    cursor: datetime | None = None
    seen: list[str] = field(default_factory=list)
    verification_cursor: datetime | None = None
    verification_seen: list[str] = field(default_factory=list)

    def checkpoint(self) -> dict[str, Any]:
        return {
            "at": self.cursor.isoformat() if self.cursor else None,
            "seen": self.seen,
            "verified_at": (
                self.verification_cursor.isoformat() if self.verification_cursor else None
            ),
            "verified_seen": self.verification_seen,
            "organizations": sorted(self.organizations),
            "durations": self.durations,
            "recent": [[at.isoformat(), worked] for at, worked in self.recent],
        }


def _moment(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _restore(stat: ExecutionStat | None) -> _Evidence | None:
    """Read a checkpoint back, or say it cannot be trusted.

    Every "no" here costs a full rebuild, which is always correct and never
    wrong -- only slower. That asymmetry is deliberate: this function is
    allowed to be conservative, it is not allowed to be optimistic.
    """
    if stat is None or not stat.checkpoint:
        return None
    saved: dict[str, Any] = stat.checkpoint
    seen = [str(value) for value in (saved.get("seen") or ())]
    verified_seen = [str(value) for value in (saved.get("verified_seen") or ())]
    if len(seen) > BOUNDARY_LIMIT or len(verified_seen) > BOUNDARY_LIMIT:
        return None
    return _Evidence(
        successful=stat.successful_runs,
        failed=stat.failed_runs,
        organizations={str(value) for value in (saved.get("organizations") or ())},
        durations=[int(value) for value in (saved.get("durations") or ())],
        failure_modes=dict(stat.failure_modes or {}),
        recent=[
            (datetime.fromisoformat(at), bool(worked)) for at, worked in (saved.get("recent") or ())
        ],
        level=VerificationLevel(stat.verification_level),
        last_verified=stat.last_verified_at,
        cursor=_moment(saved.get("at")),
        seen=seen,
        verification_cursor=_moment(saved.get("verified_at")),
        verification_seen=verified_seen,
    )


_EXECUTION_COLUMNS = (
    Execution.id,
    Execution.status,
    Execution.duration_ms,
    Execution.organization_id,
    Execution.error,
    FINISHED_AT.label("finished_at"),
)

# `populate_existing`, because every write to this table is a Core upsert and
# the ORM does not know it happened. Without it a session that has already read
# a version's stats keeps handing back the copy it read -- so the checkpoint the
# next call folds on to, and the row the caller is answered with, would both be
# one recompute out of date. That is not a caching nicety: the two calls in one
# request path are exactly this shape.
_STAT = select(ExecutionStat).execution_options(populate_existing=True)

_VERIFICATION_COLUMNS = (
    Verification.id,
    Verification.execution_id,
    Verification.passed,
    Verification.level,
    Verification.created_at,
)


def _absorb(state: _Evidence, executions: Any, verifications: Any) -> None:
    """Fold a batch of immutable rows into the running answer.

    Used by both paths, so what the numbers *are* has exactly one definition.
    The batch is the whole history in a rebuild and one run in a fold, and
    neither caller gets to describe a row differently from the other.
    """
    successful_ids: set[str] = set()
    for row in executions:
        worked = bool(row.verified) and row.status == ExecutionStatus.SUCCEEDED
        if worked:
            state.successful += 1
            state.organizations.add(row.organization_id)
            successful_ids.add(row.id)
            if row.duration_ms is not None:
                state.durations.append(row.duration_ms)
        else:
            state.failed += 1
            key = row.error or (
                "unverified" if row.status == ExecutionStatus.SUCCEEDED else str(row.status)
            )
            state.failure_modes[key] = state.failure_modes.get(key, 0) + 1
        state.recent.append((row.finished_at, worked))
        if state.cursor is None or row.finished_at > state.cursor:
            state.cursor, state.seen = row.finished_at, [row.id]
        elif row.finished_at == state.cursor:
            state.seen.append(row.id)

    for row in verifications:
        if row.passed:
            if state.last_verified is None or row.created_at > state.last_verified:
                state.last_verified = row.created_at
            # The strongest verifier that actually passed, for a run that
            # actually worked. Levels are only ever added -- verifications are
            # append-only and a terminal execution is immutable -- so carrying
            # the maximum forward is exactly what a rescan would find.
            if row.execution_id in successful_ids:
                level = VerificationLevel(row.level)
                if VERIFICATION_STRENGTH[level] > VERIFICATION_STRENGTH[state.level]:
                    state.level = level
        if state.verification_cursor is None or row.created_at > state.verification_cursor:
            state.verification_cursor, state.verification_seen = row.created_at, [row.id]
        elif row.created_at == state.verification_cursor:
            state.verification_seen.append(row.id)

    state.durations = state.durations[-DURATION_SAMPLES:]
    state.recent = state.recent[-QUARANTINE_WINDOW:]


async def _rebuild(db: AsyncSession, experience_version_id: str) -> _Evidence:
    """The definition: one version's evidence, from the source rows, from zero.

    This is the O(history) scan decision 57 took off the request path. It is
    still what the numbers *mean*, it still runs whenever a fold cannot be
    proven safe, and the scheduler runs it on a clock -- so a checkpoint that
    somehow diverged is corrected without anybody having noticed it had.
    """
    passed_ids = (
        select(Verification.execution_id)
        .where(
            Verification.experience_version_id == experience_version_id,
            Verification.passed.is_(True),
        )
        .scalar_subquery()
    )
    executions = (
        await db.execute(
            select(*_EXECUTION_COLUMNS, Execution.id.in_(passed_ids).label("verified"))
            .where(
                Execution.experience_version_id == experience_version_id,
                Execution.status.in_([s.value for s in TERMINAL]),
                # A replay is not an observation. It is not a success, it is
                # not a failure, and it is not a duration: the milliseconds on
                # a cached row belong to a run that happened on another machine
                # on another day, so counting one would misstate the percentile
                # as well as the count. Dropping the row here keeps it out of
                # every number derived below -- both counts, the durations, the
                # failure modes, the distinct organizations and therefore the
                # confidence -- rather than out of one of them (DECISIONS 51).
                Execution.cached.is_(False),
            )
            .order_by(FINISHED_AT, Execution.id)
        )
    ).all()
    verifications = (
        await db.execute(
            select(*_VERIFICATION_COLUMNS)
            .where(Verification.experience_version_id == experience_version_id)
            .order_by(Verification.created_at, Verification.id)
        )
    ).all()

    state = _Evidence()
    _absorb(state, executions, verifications)
    return state


async def _extend(db: AsyncSession, experience_version_id: str, state: _Evidence) -> bool:
    """Fold everything since the checkpoint. False means "rebuild instead".

    The reads are bounded by what has happened since the last call -- on the
    request path, the one run that just finished -- and not by how many runs
    came before it.
    """
    verified = (
        select(Verification.id)
        .where(Verification.execution_id == Execution.id, Verification.passed.is_(True))
        .exists()
    )
    conditions: list[Any] = [
        Execution.experience_version_id == experience_version_id,
        Execution.status.in_([s.value for s in TERMINAL]),
        Execution.cached.is_(False),
    ]
    if state.cursor is not None:
        # `>=` and then subtract the ids already folded, rather than `>`: two
        # runs can finish in the same instant, and a strict cursor would drop
        # the second one for good.
        conditions.append(FINISHED_AT >= state.cursor)  # noqa: SIM300 - a column, not a literal
        if state.seen:
            conditions.append(Execution.id.notin_(state.seen))
    executions = (
        await db.execute(
            select(*_EXECUTION_COLUMNS, verified.label("verified"))
            .where(*conditions)
            .order_by(FINISHED_AT, Execution.id)
        )
    ).all()

    since: list[Any] = [Verification.experience_version_id == experience_version_id]
    if state.verification_cursor is not None:
        since.append(Verification.created_at >= state.verification_cursor)
        if state.verification_seen:
            since.append(Verification.id.notin_(state.verification_seen))
    verifications = (
        await db.execute(
            select(*_VERIFICATION_COLUMNS)
            .where(*since)
            .order_by(Verification.created_at, Verification.id)
        )
    ).all()

    fresh = {row.id for row in executions}
    if any(row.passed and row.execution_id not in fresh for row in verifications):
        # A run that was already counted has just been verified, which moves it
        # from failed to successful and changes an organization count, a
        # duration sample and a failure mode. Nothing in the checkpoint can
        # express that, so the checkpoint is abandoned rather than patched.
        # This is `POST /executions/{id}/verify` against an older run, and it
        # is rare: the ordinary path verifies inside the same transaction that
        # records the run.
        return False

    _absorb(state, executions, verifications)
    return True


async def recompute(db: AsyncSession, experience_version_id: str) -> ExecutionStat:
    """Bring one version's evidence up to date, and act on what it says.

    Folds on to the stored checkpoint wherever that is provably identical to a
    rescan, and rebuilds from the immutable rows wherever it is not. Either way
    the answer is the same answer; only the cost differs (DECISIONS 57).
    """
    stat_row = (
        await db.execute(_STAT.where(ExecutionStat.experience_version_id == experience_version_id))
    ).scalar_one_or_none()

    state = _restore(stat_row)
    if state is None or not await _extend(db, experience_version_id, state):
        state = await _rebuild(db, experience_version_id)

    distinct_organizations = await independent_organizations(db, state.organizations)
    durations = sorted(state.durations)
    total = state.successful + state.failed
    experience_id = (
        str(stat_row.experience_id)
        if stat_row is not None
        else await _experience_id(db, experience_version_id)
    )
    stat: dict[str, Any] = {
        "experience_version_id": experience_version_id,
        "experience_id": experience_id,
        "successful_runs": state.successful,
        "failed_runs": state.failed,
        "median_duration_ms": _percentile(durations, 0.50),
        "p95_duration_ms": _percentile(durations, 0.95),
        "success_rate": (state.successful / total) if total else 0.0,
        "confidence": confidence_score(
            state.successful, state.failed, distinct_organizations, state.level
        ),
        "distinct_organizations": distinct_organizations,
        "verification_level": state.level,
        "failure_modes": state.failure_modes,
        "last_verified_at": state.last_verified,
        "checkpoint": state.checkpoint(),
        "updated_at": now(),
    }

    statement = insert(ExecutionStat).values(**stat)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[ExecutionStat.experience_version_id],
            set_={k: v for k, v in stat.items() if k != "experience_version_id"},
        )
    )

    await _grade(db, experience_version_id, state, distinct_organizations)

    return (
        await db.execute(_STAT.where(ExecutionStat.experience_version_id == experience_version_id))
    ).scalar_one()


async def rebuild(db: AsyncSession, experience_version_id: str) -> ExecutionStat:
    """Recompute from the source rows, ignoring whatever the checkpoint says.

    The reconciliation half of decision 57, and the thing that keeps decision
    11 true: whatever the fold believes, this is the definition, and the
    scheduler runs it on a clock. Also the answer to "how do I know the numbers
    are right" -- run this and compare.
    """
    await db.execute(
        update(ExecutionStat)
        .where(ExecutionStat.experience_version_id == experience_version_id)
        .values(checkpoint=None)
    )
    return await recompute(db, experience_version_id)


async def _experience_id(db: AsyncSession, experience_version_id: str) -> str:
    value = (
        await db.execute(
            select(Execution.experience_id)
            .where(Execution.experience_version_id == experience_version_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if value is not None:
        return str(value)
    return str(
        (
            await db.execute(
                select(ExperienceVersion.experience_id).where(
                    ExperienceVersion.id == experience_version_id
                )
            )
        ).scalar_one()
    )


def rotten(recent: list[tuple[datetime, bool]]) -> bool:
    """Has this stopped working, recently enough to be worth acting on?

    Two gates, and both are load-bearing. The rate is over the most recent
    QUARANTINE_WINDOW runs rather than over all of history, because an
    Experience with nine hundred successes whose last twenty runs all failed is
    broken *now* and its lifetime success rate says otherwise.

    The second gate is recency, and it is `ranking.recency_score` rather than a
    second opinion about what "old" means: fifty failures from two years ago
    are already worth nothing to the ranker, and quarantining on them would
    withdraw something from recall on evidence nobody can reproduce. Rot has to
    be fresh to count as rot.
    """
    if len(recent) < QUARANTINE_MIN_RUNS:
        return False
    failures = [at for at, worked in recent if not worked]
    if len(failures) / len(recent) < QUARANTINE_AT:
        return False
    return recency_score(max(failures)) > 0.0


def recovered(recent: list[tuple[datetime, bool]]) -> bool:
    """Has it started working again, by enough of a margin to be believed?

    Deliberately not the complement of `rotten`. The gap between RELEASE_AT and
    QUARANTINE_AT is the whole anti-thrash mechanism: one lucky run must not
    undo a quarantine, and one unlucky run must not re-impose it.
    """
    if len(recent) < QUARANTINE_MIN_RUNS:
        return False
    failures = sum(1 for _, worked in recent if not worked)
    return failures / len(recent) <= RELEASE_AT


async def _grade(
    db: AsyncSession, experience_version_id: str, state: _Evidence, organizations: int
) -> None:
    """Move the Experience's status to match what its current version's runs say.

    `organizations` is the *independent* count that `recompute` just stored, not
    `len(state.organizations)`. Grading off the raw set was how this first
    shipped, and it left the two halves of one decision disagreeing: recall
    said `consider` from the collapsed count while `status` still said
    `verified` from the raw one. `verified` is a claim that somebody else
    proved it, so reading it off a number that counts one party twice is the
    exact claim decision 70 exists to stop making.

    Both directions live here because they are one decision, and splitting them
    is how a corpus ends up able to promote and not demote -- which is what
    this was until decision 56. Only the *current* version votes: recall offers
    nothing else, and an old version rotting is not a reason to withdraw the
    one people are actually being handed.
    """
    row = (
        await db.execute(
            select(Experience, ExperienceVersion.version)
            .join(ExperienceVersion, ExperienceVersion.experience_id == Experience.id)
            .where(ExperienceVersion.id == experience_version_id)
        )
    ).first()
    if row is None:
        return
    experience, version_number = row

    if version_number == experience.latest_version:
        if experience.status == ExperienceStatus.QUARANTINED:
            # An operator's quarantine is never lifted by a run of luck. It was
            # a judgement about something the runs cannot see -- a credential
            # baked into an image, a licence problem, an artifact that works
            # perfectly and should not be recommended -- so only an operator
            # takes it back (DECISIONS 56).
            if not (experience.quarantine or {}).get("manual") and recovered(state.recent):
                experience.status = ExperienceStatus.CANDIDATE
                experience.quarantine = None
                experience.updated_at = now()
        elif experience.status != ExperienceStatus.DEPRECATED and rotten(state.recent):
            quarantine(
                experience,
                reason=(
                    f"{sum(1 for _, worked in state.recent if not worked)} of the last "
                    f"{len(state.recent)} runs of version {version_number} failed"
                ),
                by="evidence",
                manual=False,
            )
            return

    if state.successful and corroborated(organizations):
        _promote(experience, state.level, state.last_verified)
    else:
        _withdraw(experience)


def quarantine(experience: Experience, reason: str, by: str, manual: bool) -> None:
    """Take an Experience out of recall, and record why on the row.

    The reason is stored the way decision 53 stores a tier grant's: on the row
    it justifies, next to who did it and when, because a quarantine with no
    stated cause cannot be audited and cannot be reversed with any confidence.
    `manual` is what stops an operator's judgement being undone by a run of
    luck -- see `_grade`.
    """
    experience.status = ExperienceStatus.QUARANTINED
    experience.quarantine = {
        "reason": reason,
        "by": by,
        "manual": manual,
        "at": now().isoformat(),
    }
    experience.updated_at = now()


def _promote(
    experience: Experience,
    level: VerificationLevel,
    last_verified: datetime | None,
) -> None:
    """Independently corroborated executions move candidate to verified.

    It used to be the first proven run, which meant whoever recorded an
    Experience could also promote it: declare `exit_code` as the verifier, ship
    an artifact that exits 0, run it once, and the registry started telling
    every other agent to use it. Spec section 22 describes a richer policy;
    this is the part of it that closes that door.

    The level recorded is the strongest verifier that actually passed, so an
    Experience corroborated only by exit codes reads "claimed", not "proven".

    Still refuses a quarantined Experience, and now that something actually
    writes that status the refusal is load-bearing rather than theoretical: a
    version whose recent runs are failing must not be promoted straight back
    out of quarantine by the same call that put it there.
    """
    if experience.status == ExperienceStatus.QUARANTINED:
        return
    experience.status = ExperienceStatus.VERIFIED
    experience.verification_level = level
    experience.updated_at = last_verified or now()


def _withdraw(experience: Experience) -> None:
    """Take back `verified` when the corroboration behind it is gone.

    `_promote` was one-way, which was survivable while the only thing that
    could change was runs accumulating -- evidence never un-happens. Decision
    70 made the *count* mutable: naming an organization as first-party
    collapses it into the operator, and an Experience promoted on two
    organizations that turn out to be one party is left asserting something
    nobody proved. Recall already stopped recommending it; the row went on
    saying `verified`, and the row is what a human reads.

    So the pair is closed the way `_grade`'s docstring says it must be. Only
    from VERIFIED, and only back to CANDIDATE -- this is "nobody independent
    has proven this yet", which is exactly what a candidate is. Quarantine and
    deprecation are somebody's judgement and are not ours to undo, and an
    Experience that never reached verified has nothing to take back.
    """
    if experience.status != ExperienceStatus.VERIFIED:
        return
    experience.status = ExperienceStatus.CANDIDATE
    experience.verification_level = VerificationLevel.UNVERIFIED
    experience.updated_at = now()


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    index = min(len(values) - 1, int(round(fraction * (len(values) - 1))))
    return values[index]


def as_dict(stat: ExecutionStat) -> dict[str, Any]:
    return {
        "successful_runs": stat.successful_runs,
        "failed_runs": stat.failed_runs,
        "success_rate": stat.success_rate,
        "confidence": stat.confidence,
        "last_verified_at": stat.last_verified_at,
        "median_duration_ms": stat.median_duration_ms,
        "p95_duration_ms": stat.p95_duration_ms,
        "distinct_organizations": stat.distinct_organizations,
        "failure_modes": dict(stat.failure_modes or {}),
    }

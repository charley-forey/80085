"""Lineage, read back at last -- and read back without leaking.

Six relations have been written on every version since the first migration and
read by nothing. Turning them into a traversal is easy; turning them into a
traversal that cannot be used as an existence oracle is the interesting half,
because a lineage id is free text written by a stranger and nothing validates
it. An Experience can name another organization's private id in `improves`
today, and resolving that naively answers a question the caller was never
entitled to ask.

The two claims worth pinning here are that resolution stops (`A supersedes B
supersedes A` is writable) and that an invisible target is reported the same
way as one that never existed. The SQL predicate that decides which is which
is asserted against a real database in
tests/integration/test_lineage.py -- a claim about a `WHERE` clause does not
survive being mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from boobs_api import routes
from boobs_common.clock import now
from boobs_domain.enums import ExperienceStatus, VerificationLevel, Visibility
from boobs_domain.protocols import Principal
from boobs_schemas.tables import Experience, ExperienceVersion
from boobs_security.keys import Scope

CALLER = Principal(
    organization_id="org_mine", agent_id="agt_mine", scopes=frozenset({Scope.EXPERIENCES_READ})
)


def _experience(experience_id: str) -> Experience:
    return Experience(
        id=experience_id,
        organization_id="org_theirs",
        goal_statement=f"do the {experience_id} thing",
        goal_intent="do_thing",
        tags=[],
        status=ExperienceStatus.CANDIDATE,
        verification_level=VerificationLevel.UNVERIFIED,
        visibility=Visibility.PUBLIC,
        latest_version=2,
        created_by="agt_theirs",
        created_at=now(),
        updated_at=now(),
    )


def _wire(monkeypatch: pytest.MonkeyPatch, graph: dict[str, dict[str, str]], visible: set[str]):
    """Stand in for the two database reads, and for nothing else.

    The walk itself -- the visited set, the depth, the budget, what an
    unresolved node carries -- is the real code. `visible` is what the real
    `visibility_clause` decides; that it decides it correctly is the
    integration test's job.
    """

    class Repository:
        def __init__(self, _db: object) -> None:
            pass

        async def get(self, _principal: Principal, experience_id: str) -> object:
            return SimpleNamespace(id=experience_id)

    async def edges(_db: object, ids: list[str]) -> list[tuple[str, str, str]]:
        return [
            (source, relation, graph[source][relation])
            for source in ids
            if source in graph
            for relation in routes.LINEAGE_RELATIONS
            if graph[source].get(relation)
        ]

    async def resolve(_db: object, _principal: Principal, ids: list[str]) -> dict[str, Experience]:
        return {i: _experience(i) for i in ids if i in visible}

    monkeypatch.setattr(routes, "ExperienceRepository", Repository)
    monkeypatch.setattr(routes, "_lineage_edges", edges)
    monkeypatch.setattr(routes, "_visible_experiences", resolve)


async def _walk(root: str = "exp_root", depth: int = 3) -> Any:
    """Called straight, so `depth` is passed explicitly -- FastAPI's default is
    a `Query` marker until a request goes through the framework."""
    return await routes.get_experience_lineage(
        experience_id=root,
        db=None,  # type: ignore[arg-type]
        principal=CALLER,
        depth=depth,
    )


# --------------------------------------------------------------- termination


async def test_a_cycle_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    """`A supersedes B supersedes A` is writable today, and must not hang.

    Breadth-first with a visited set, so B is emitted once and its edge back to
    A is dropped as already seen. The walk ends because the frontier empties,
    not because the depth ran out.
    """
    _wire(
        monkeypatch,
        {"exp_root": {"supersedes": "exp_b"}, "exp_b": {"supersedes": "exp_root"}},
        {"exp_b"},
    )
    answer = await _walk(depth=5)
    assert [node.experience_id for node in answer.nodes] == ["exp_b"]
    assert answer.truncated is False


async def test_an_experience_that_points_at_itself_terminates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shortest cycle there is, and nothing rejects it at write time."""
    _wire(monkeypatch, {"exp_root": {"improves": "exp_root"}}, {"exp_root"})
    assert (await _walk()).nodes == []


async def test_depth_bounds_the_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    """A chain is the shape lineage actually takes, so depth is the usual bound."""
    _wire(
        monkeypatch,
        {
            "exp_root": {"improves": "exp_b"},
            "exp_b": {"improves": "exp_c"},
            "exp_c": {"improves": "exp_d"},
        },
        {"exp_b", "exp_c", "exp_d"},
    )
    assert [n.experience_id for n in (await _walk(depth=2)).nodes] == ["exp_b", "exp_c"]
    assert [n.depth for n in (await _walk(depth=2)).nodes] == [1, 2]


async def test_the_node_budget_truncates_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """Six relations per node makes depth alone a 7776-node bound. It is not
    the real one: the budget is, and a caller has to be told it ran out."""
    monkeypatch.setattr(routes, "MAX_LINEAGE_NODES", 2)
    _wire(
        monkeypatch,
        {"exp_root": {"improves": "exp_a", "replaces": "exp_b", "supersedes": "exp_c"}},
        {"exp_a", "exp_b", "exp_c"},
    )
    answer = await _walk()
    assert len(answer.nodes) == 2
    assert answer.truncated is True


# ------------------------------------------------------------------- tenancy


async def test_a_private_target_and_a_missing_one_are_indistinguishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The leak this endpoint exists to not have.

    `improves` names another organization's private Experience; `forked_from`
    names an id that was never recorded. If the two answers differ in any way,
    anyone who can record can ask this endpoint whether an arbitrary id exists
    -- and the ids of private Experiences are handed to their owners in plain
    text on every record.
    """
    _wire(
        monkeypatch,
        {"exp_root": {"improves": "exp_someone_elses_private", "forked_from": "exp_never_existed"}},
        set(),
    )
    nodes = (await _walk()).nodes
    assert len(nodes) == 2
    shapes = [
        node.model_dump(exclude_none=True, exclude={"relation", "experience_id"}) for node in nodes
    ]
    assert shapes[0] == shapes[1], "an invisible target answers differently to a missing one"
    assert all(node.resolved is False and node.goal is None for node in nodes)


async def test_an_invisible_target_is_never_walked_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise the graph behind a private node is reachable by going around it."""
    _wire(
        monkeypatch,
        {
            "exp_root": {"improves": "exp_private"},
            "exp_private": {"improves": "exp_secret"},
        },
        {"exp_secret"},
    )
    reached = [node.experience_id for node in (await _walk(depth=5)).nodes]
    assert reached == ["exp_private"]
    assert "exp_secret" not in reached


async def test_a_visible_target_resolves_to_something_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the endpoint: an id alone is not a reason to do anything."""
    _wire(monkeypatch, {"exp_root": {"supersedes": "exp_old"}}, {"exp_old"})
    (node,) = (await _walk()).nodes
    assert node.resolved is True
    assert node.relation == "supersedes"
    assert node.goal == "do the exp_old thing"
    assert node.latest_version == 2


# ---------------------------------------------------------- what is surfaced


def test_the_experience_response_carries_only_the_relations_that_were_set() -> None:
    """A caller could not read back the lineage of their own Experience at all.

    Sparse, because five nulls on every experience read cost every caller
    tokens to learn nothing -- and this is read by agents that pay per field.
    """
    experience = _experience("exp_root")
    version = ExperienceVersion(
        id="ver_1",
        experience_id=experience.id,
        organization_id=experience.organization_id,
        version=1,
        artifact_id="art_1",
        lineage={"improves": "exp_older", "forked_from": None, "supersedes": ""},
        search_text="do the thing",
        created_by=experience.created_by,
        created_at=now(),
    )
    response = routes._experience_response(
        experience, version, "sha256:" + "a" * 64, routes.Evidence()
    )
    assert response.lineage == {"improves": "exp_older"}


def test_the_traversal_reads_its_relations_off_the_write_model() -> None:
    """So a seventh relation is traversable the day it is recordable."""
    assert routes.LINEAGE_RELATIONS == (
        "derived_from",
        "forked_from",
        "improves",
        "replaces",
        "supersedes",
        "failed_variant_of",
    )

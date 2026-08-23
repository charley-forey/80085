"""The API must never run an artifact. Nothing enforced that.

The whole trust model rests on it. The API holds the database credentials, the
object-store credentials and every tenant's data; the worker holds one scoped
key and no privileged path of any kind (DECISIONS 17). That separation is what
makes it acceptable to run code an anonymous author uploaded -- the process
that runs hostile code is the one with nothing worth stealing.

Today the property is true *by absence*: no module under `apps/api` imports
`boobs_execution`, and `apps/api/pyproject.toml` does not depend on it. Absence
is not enforcement. One `from boobs_execution import runtime` in a route --
added in good faith, to "just verify it inline" -- moves artifact execution
into the process holding every credential, and no test, type check or lint rule
in this repo would have said a word.

That is the same shape as every other serious finding here: not a thing that
broke, but a thing believed and never checked. So this checks it.

It reads the AST rather than grepping, so a name inside a string or a comment
cannot fail it and a real import cannot hide from it.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[2] / "apps" / "api"
SOURCES = sorted((API / "src").rglob("*.py"))

# Importing any of these into the API process means it can start a sandbox.
# `boobs_execution` is the runtime package itself; the rest are how someone
# would reach a container without it.
FORBIDDEN_PREFIXES = ("boobs_execution", "docker", "e2b", "subprocess")


def _imported_modules(source: Path) -> set[str]:
    """Every module name this file imports, however it imports it."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        # `from . import x` has no module; a relative import cannot reach
        # outside apps/api, so it is not a way to smuggle a runtime in.
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def _forbidden(name: str) -> str | None:
    root = name.split(".")[0]
    return next((p for p in FORBIDDEN_PREFIXES if root == p), None)


def test_there_is_something_to_check() -> None:
    """A test that silently checked zero files would be the failure it exists
    to prevent."""
    assert SOURCES, f"no python sources found under {API / 'src'}"


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_no_api_module_can_start_a_sandbox(source: Path) -> None:
    offenders = {name: prefix for name in _imported_modules(source) if (prefix := _forbidden(name))}
    assert not offenders, (
        f"{source.relative_to(API)} imports {sorted(offenders)}, which puts artifact "
        "execution in the process that holds the database and object-store "
        "credentials. Artifacts run on the worker, which holds one scoped API key "
        "and nothing worth stealing (DECISIONS 17). If the API genuinely needs a "
        "result, it asks the worker for one -- it does not run the container."
    )


def test_the_api_does_not_even_depend_on_the_execution_package() -> None:
    """Belt and braces, and the cheaper of the two to keep true.

    The import check above only sees code that exists. This one fails at the
    moment someone makes the runtime *reachable*, which is the step before
    anyone writes the import.
    """
    manifest = tomllib.loads((API / "pyproject.toml").read_text(encoding="utf-8"))
    declared = manifest["project"]["dependencies"]
    assert not [d for d in declared if "execution" in d], (
        f"apps/api declares a dependency on the execution package: {declared}. "
        "The API is not permitted to run artifacts, so it has no reason to be "
        "able to import a sandbox runtime at all."
    )

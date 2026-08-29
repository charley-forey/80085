"""`ruff format --check .` is a repo check (AGENTS.md, ci.yml) but nothing
under `tests/` ran it, so an unformatted file could land on main and only
fail in CI -- or not at all, if CI's formatting gate ever went unnoticed. A
migration in 0014_stale_disputed_and_blast_radius.py did exactly that: one
`op.add_column(...)` call was never reformatted after editing, and
`ruff check` has nothing to say about formatting. This makes the property a
unit test instead of something only CI enforces.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repo_is_ruff_formatted() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "ruff format --check found unformatted files:\n"
        f"{result.stdout}{result.stderr}\n"
        "Run `uv run ruff format .` before committing."
    )

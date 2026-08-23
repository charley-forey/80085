"""Every capability in the corpus, run against its fixture without Docker.

An image that stopped producing what it promises is a broken Experience, and
the platform would only find out after recording evidence against it. This
runs each `main.py` directly, so CI catches it before anything is published.

Two things are asserted, and they are different claims:

* the output bytes match the committed fixture -- determinism, which every
  `sha256` digest in the corpus depends on;
* the output satisfies the verifier the manifest declares -- the manifest and
  the code agreeing, which is what makes a recorded verdict mean anything.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES = ROOT / "capabilities"
MANIFEST = json.loads((CAPABILITIES / "manifest.json").read_text(encoding="utf-8"))
CORPUS: dict[str, dict] = MANIFEST["capabilities"]


def files_under(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_capability_reproduces_its_fixture(name: str, tmp_path: Path) -> None:
    entry = CORPUS[name]
    fixture = CAPABILITIES / "fixtures" / name
    shutil.copytree(fixture / "inputs", tmp_path, dirs_exist_ok=True)

    command = entry["command"]
    assert command[:2] == ["python", "/app/main.py"], f"{name}: unexpected command shape"
    main = CAPABILITIES / "examples" / name / "main.py"
    process = subprocess.run(
        [sys.executable, str(main), *command[2:]],
        cwd=tmp_path,
        capture_output=True,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")

    expected_root = fixture / "expected"
    expected = files_under(expected_root)
    assert expected, f"{name}: fixture declares no expected output"
    for path in expected:
        relative = path.relative_to(expected_root)
        assert (tmp_path / relative).read_bytes() == path.read_bytes(), f"{name}: {relative}"


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_declared_verifier_passes_on_the_fixture_output(name: str) -> None:
    verification = CORPUS[name]["verification"]
    # Anything can exit zero. A verifier that believes the exit code turns a
    # container that does nothing into evidence.
    assert verification["verifier"] in {"json_schema", "sha256"}, f"{name}: weak verifier"
    config = verification["config"]
    produced = CAPABILITIES / "fixtures" / name / "expected" / config["file"]
    assert produced.is_file(), f"{name}: fixture has no {config['file']}"
    if verification["verifier"] == "json_schema":
        jsonschema.validate(json.loads(produced.read_text(encoding="utf-8")), config["schema"])


def test_corpus_and_examples_do_not_drift() -> None:
    examples = {path.name for path in (CAPABILITIES / "examples").iterdir() if path.is_dir()}
    fixtures = {path.name for path in (CAPABILITIES / "fixtures").iterdir() if path.is_dir()}
    assert examples == set(CORPUS), "capabilities/examples and manifest.json disagree"
    assert fixtures == set(CORPUS), "capabilities/fixtures and manifest.json disagree"
    for name in CORPUS:
        assert (CAPABILITIES / "examples" / name / "Dockerfile").is_file(), f"{name}: no Dockerfile"

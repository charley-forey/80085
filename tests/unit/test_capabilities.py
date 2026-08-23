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
from decimal import Decimal
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
        blob = path.read_bytes()
        # A fixture recorded on Windows carries CRLF, .gitattributes stops git
        # from ever normalising it, and the file then only matches the machine
        # that produced it. Caught in CI once; cheaper to assert than rediscover.
        assert b"\r\n" not in blob, f"{name}: {relative} has CRLF; fixtures are LF"
        assert (tmp_path / relative).read_bytes() == blob, f"{name}: {relative}"


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


def run(name: str, work: Path, arguments: list[str], **inputs: bytes) -> dict:
    """Run one capability on inputs written here rather than on its fixture.

    The fixture tests above prove a capability still produces the bytes it did
    when it was recorded. These prove the properties that hold for *every*
    input, which is what an agent recalling the capability is actually relying
    on and what a single fixture can never establish.
    """
    for filename, blob in inputs.items():
        (work / filename.replace("__", ".")).write_bytes(blob)
    process = subprocess.run(
        [sys.executable, str(CAPABILITIES / "examples" / name / "main.py"), *arguments],
        cwd=work,
        capture_output=True,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    return json.loads((work / "result.json").read_text(encoding="utf-8"))


def test_mojibake_repair_leaves_repaired_text_alone(tmp_path: Path) -> None:
    # Run it on its own output. A repair that is not idempotent gets applied
    # twice the moment two agents chain it, and the second pass eats text that
    # was already correct.
    expected = CAPABILITIES / "fixtures" / "mojibake_repair" / "expected" / "output.txt"
    repaired = expected.read_bytes()
    result = run("mojibake_repair", tmp_path, ["input.txt", "output.txt"], input__txt=repaired)
    assert result["passes"] == 0
    assert (tmp_path / "output.txt").read_bytes() == repaired


@pytest.mark.parametrize(
    ("total", "weights", "currency"),
    [
        ("100.00", [1, 1, 1], "USD"),
        ("0.01", [1, 1, 1], "USD"),
        ("-100.00", [1, 1, 1], "USD"),
        ("1000", [2, 1], "JPY"),
        ("10.000", [1, 1, 1], "KWD"),
        ("99.99", [7, 11, 13, 0], "EUR"),
    ],
)
def test_money_allocate_shares_sum_to_the_total(
    total: str, weights: list[int], currency: str, tmp_path: Path
) -> None:
    request = json.dumps({"total": total, "weights": weights, "currency": currency})
    result = run("money_allocate", tmp_path, ["input.json"], input__json=request.encode())
    assert sum(Decimal(share) for share in result["allocations"]) == Decimal(total)
    assert len(result["allocations"]) == len(weights)


def test_date_parse_refuses_to_pick_a_day_month_order(tmp_path: Path) -> None:
    values = ["03/04/2024", "01/02/2024", "13/04/2024"]
    result = run(
        "date_parse",
        tmp_path,
        ["input.json"],
        input__json=json.dumps({"values": values}).encode(),
    )
    ambiguous = [item for item in result["values"] if item["ambiguous"]]
    assert [item["input"] for item in ambiguous] == values[:2]
    assert all(item["iso"] is None for item in ambiguous)
    assert all(len(item["interpretations"]) == 2 for item in ambiguous)
    # ... and the caller's own knowledge is the only thing that resolves it.
    resolved = run(
        "date_parse",
        tmp_path,
        ["input.json"],
        input__json=json.dumps({"values": values, "prefer": "dmy"}).encode(),
    )
    assert [item["iso"] for item in resolved["values"]] == [
        "2024-04-03",
        "2024-02-01",
        "2024-04-13",
    ]

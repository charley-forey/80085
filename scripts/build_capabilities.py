"""Build the example capability images and record their digests.

80085 executes artifacts by digest only, so a build is not finished until we
know the digest the registry assigned. That digest -- not the tag -- is what
gets recorded on an Experience.

    uv run python scripts/build_capabilities.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "capabilities" / "examples"
OUTPUT = ROOT / "capabilities" / "digests.json"
REGISTRY = os.environ.get("ARTIFACT_REGISTRY", "localhost:5000")


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"$ {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def build(name: str, path: Path) -> str:
    repository = f"{REGISTRY}/80085/{name}"
    tag = f"{repository}:build"
    print(f"building {name}...", flush=True)
    run("docker", "build", "--quiet", "-t", tag, str(path))
    run("docker", "push", "--quiet", tag)
    digests = run("docker", "inspect", "--format", "{{json .RepoDigests}}", tag)
    for reference in json.loads(digests):
        if reference.startswith(repository + "@"):
            return str(reference)
    raise SystemExit(f"{name}: registry returned no digest for {tag}")


def main() -> int:
    if not EXAMPLES.is_dir():
        raise SystemExit(f"no examples at {EXAMPLES}")
    built = {
        path.name: build(path.name, path)
        for path in sorted(EXAMPLES.iterdir())
        if (path / "Dockerfile").is_file()
    }
    OUTPUT.write_text(json.dumps(built, indent=2) + "\n")
    for name, reference in built.items():
        print(f"  {name}: {reference}")
    print(f"\nwrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

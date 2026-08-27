"""Agent-in-the-loop control vs treatment: the claim `run.py` cannot make.

`run.py` measures the cost of *producing and running a verified artifact*, and
its honest finding is that for a small stdlib capability that cost is a wash --
roughly 1.0x, because both arms are dominated by the same sandbox spin-up. That
result is true and it is not the product's claim.

The claim is about the reasoning that never happens: an agent that inherits a
proven solution should not have to derive one. That cost is an LLM's tokens,
tool calls and wall clock, which `run.py` says plainly it does not measure.

    CONTROL   -- a real agent, a real sandbox, no 80085. Write the code,
                 run it, produce the output.
    TREATMENT -- the same agent, the same sandbox, the same prompt, with the
                 80085 MCP tools attached.

Both arms end in the same place and are judged the same way: the harness -- not
the agent -- runs a check inside the container afterwards and hands the result
to the same `RegistryVerifier` the platform uses. An arm that does not pass
verification does not count, however fast it was.

    ANTHROPIC_API_KEY=... uv run python benchmarks/agent.py

Needs Docker, and for the treatment arm an API with a worker attached.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# TASKS carries the goals, inputs and verifier specs both benchmarks judge by.
# Redefining them here would let the two harnesses drift into measuring
# different things while reporting the same task names.
from benchmarks.run import TASKS, Task  # noqa: E402

MODEL = os.environ.get("BENCHMARK_MODEL", "claude-opus-5")
REPEATS = int(os.environ.get("BENCHMARK_REPEATS", "3"))
MCP_URL = os.environ.get("BOOBS_MCP_URL", "https://mcp.80085.ai/mcp")
API_URL = os.environ.get("BOOBS_API_URL", "https://api.80085.ai")
IMAGE = os.environ.get("BENCHMARK_AGENT_IMAGE", "python:3.13-slim")
RESULTS = ROOT / "benchmarks" / "results-agent.json"

# The agent's workspace. Same path in both arms so the prompt is identical.
WORK = "/work"

# What the *harness* runs after the agent stops, to decide whether the arm
# succeeded. The agent never sees these and cannot report its own verdict.
#
# Each one feeds a SandboxResult that goes to the task's own verifier spec:
# a json_schema task is judged on the file this collects, and json_to_csv --
# whose spec is `exit_code` -- is judged on this command's exit code, which is
# a real check of the artifact rather than of whatever the agent last ran.
CHECKS: dict[str, tuple[list[str], str | None]] = {
    "csv_to_json": (["test", "-s", f"{WORK}/output.json"], "output.json"),
    "json_to_csv": (
        [
            "python",
            "-c",
            "import csv,sys; rows=list(csv.reader(open('/work/output.csv')));"
            " sys.exit(0 if len(rows) > 1 and len(rows[0]) > 1 else 1)",
        ],
        None,
    ),
    "json_validate": (["test", "-s", f"{WORK}/result.json"], "result.json"),
}

PROMPT = """You are working in a Linux container. Your working directory is {work}.

Task: {goal}

These files are already staged in {work}: {inputs}

Produce {outputs} in {work}. There is no network access from your shell, and no
packages can be installed -- the Python standard library is all there is.

Stop when the file exists and is correct."""

SYSTEM = """You are an autonomous engineer. Work until the task is done, then stop.

Do not ask for confirmation and do not explain your plan before acting -- run
the tools. When you believe the task is complete, say so in one sentence."""


# ------------------------------------------------------------------ container


class Workspace:
    """A throwaway container both arms get an identical copy of.

    No network: the capabilities are stdlib-only by construction, and an agent
    that could `pip install` would be measuring PyPI rather than either arm.
    """

    def __init__(self, task: Task, label: str) -> None:
        self.name = f"bench-agent-{label}-{task.name}-{int(time.time() * 1000)}"
        self.task = task

    def __enter__(self) -> Workspace:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--network",
                "none",
                "--name",
                self.name,
                "-w",
                WORK,
                IMAGE,
                "sleep",
                "1800",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.sh(f"mkdir -p {WORK}")
        for filename, blob in self.task.inputs.items():
            staged = Path(os.environ.get("TMPDIR", "/tmp")) / filename
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(blob)
            subprocess.run(
                ["docker", "cp", str(staged), f"{self.name}:{WORK}/{filename}"],
                capture_output=True,
                check=True,
            )
        return self

    def __exit__(self, *_: object) -> None:
        subprocess.run(["docker", "kill", self.name], capture_output=True)

    def sh(self, command: str, timeout: int = 120) -> tuple[str, int]:
        """Run a shell command in the workspace. Output is capped: an agent
        that cats a large file should not blow the context window it is being
        measured on."""
        try:
            done = subprocess.run(
                ["docker", "exec", "-w", WORK, self.name, "sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"timed out after {timeout}s", 124
        output = (done.stdout + done.stderr)[:8000]
        return output, done.returncode

    def collect(self, filename: str | None) -> dict[str, bytes]:
        if filename is None:
            return {}
        done = subprocess.run(
            ["docker", "exec", self.name, "cat", f"{WORK}/{filename}"],
            capture_output=True,
        )
        return {filename: done.stdout} if done.returncode == 0 else {}


async def verified(workspace: Workspace, task: Task) -> bool:
    """The harness's own verdict, from the same verifier the platform uses."""
    from boobs_domain.entities import VerificationSpec
    from boobs_domain.protocols import ExecutionStatus, SandboxResult
    from boobs_verification.verifiers import RegistryVerifier

    command, wanted = CHECKS[task.name]
    done = subprocess.run(
        ["docker", "exec", "-w", WORK, workspace.name, *command],
        capture_output=True,
        text=True,
    )
    result = SandboxResult(
        status=ExecutionStatus.SUCCEEDED,
        exit_code=done.returncode,
        duration_ms=0,
        output_files=workspace.collect(wanted),
    )
    outcome = await RegistryVerifier().verify(
        result,
        VerificationSpec(verifier=task.verifier["verifier"], config=task.verifier["config"]),
    )
    return bool(outcome.passed)


# ---------------------------------------------------------------------- arms


def _outputs(task: Task) -> str:
    _, wanted = CHECKS[task.name]
    return wanted or "output.csv"


async def arm(task: Task, *, with_80085: bool, key: str | None) -> dict[str, Any]:
    """One agent run. Returns wall clock, tokens, tool calls and the verdict."""
    import anthropic
    from anthropic import beta_tool

    client = anthropic.Anthropic()
    started = time.monotonic()

    with Workspace(task, "treatment" if with_80085 else "control") as workspace:

        @beta_tool
        def bash(command: str) -> str:
            """Run a shell command in the working directory and return its output.

            Args:
                command: The shell command to run.
            """
            output, code = workspace.sh(command)
            return f"exit {code}\n{output}"

        tools: list[Any] = [bash]
        extra: dict[str, Any] = {}
        if with_80085:
            # The MCP connector needs both halves: the server, and a toolset
            # entry naming it. The server runs Anthropic-side, so there is no
            # local function to implement.
            tools.append({"type": "mcp_toolset", "mcp_server_name": "80085"})
            extra = {
                "betas": ["mcp-client-2025-11-20"],
                "mcp_servers": [
                    {
                        "type": "url",
                        "url": MCP_URL,
                        "name": "80085",
                        **({"authorization_token": key} if key else {}),
                    }
                ],
            }

        runner = client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            tools=tools,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT.format(
                        work=WORK,
                        goal=task.goal,
                        inputs=", ".join(task.inputs),
                        outputs=_outputs(task),
                    ),
                }
            ],
            **extra,
        )

        tokens_in = tokens_out = calls = 0
        for message in runner:
            usage = message.usage
            tokens_in += usage.input_tokens + (usage.cache_read_input_tokens or 0)
            tokens_out += usage.output_tokens
            calls += sum(1 for block in message.content if block.type == "tool_use")

        seconds = time.monotonic() - started
        passed = await verified(workspace, task)

    return {
        "seconds": seconds,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "tool_calls": calls,
        "verified": passed,
    }


# ------------------------------------------------------------------- harness


def median(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "seconds": statistics.median(r["seconds"] for r in runs),
        "input_tokens": int(statistics.median(r["input_tokens"] for r in runs)),
        "output_tokens": int(statistics.median(r["output_tokens"] for r in runs)),
        "tool_calls": int(statistics.median(r["tool_calls"] for r in runs)),
        # Every repeat must pass. One flake is the variance argument failing,
        # not a rounding error to take the median of.
        "verified": all(r["verified"] for r in runs),
    }


def table(rows: list[dict[str, Any]]) -> str:
    header = (
        f"{'task':<16}{'arm':>11}{'seconds':>10}{'in tok':>10}"
        f"{'out tok':>10}{'calls':>8}{'passed':>9}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        for arm_name in ("control", "treatment"):
            got = row[arm_name]
            lines.append(
                f"{row['task'] if arm_name == 'control' else '':<16}{arm_name:>11}"
                f"{got['seconds']:>9.1f}s{got['input_tokens']:>10,}"
                f"{got['output_tokens']:>10,}{got['tool_calls']:>8}"
                f"{('yes' if got['verified'] else 'NO'):>9}"
            )
    return "\n".join(lines)


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set.\n\n"
            "This benchmark needs a real model: it measures the reasoning an agent\n"
            "does or does not have to do, which is the whole point of it. Set the\n"
            "key and re-run. Do not commit a result produced without one.",
            file=sys.stderr,
        )
        return 2

    key = os.environ.get("BOOBS_API_KEY")
    if not key:
        print(
            f"BOOBS_API_KEY is not set -- minting one from {API_URL} for the treatment arm.",
            file=sys.stderr,
        )
        import httpx

        async with httpx.AsyncClient() as http:
            response = await http.post(f"{API_URL}/v1/keys", params={"label": "benchmark-agent"})
        response.raise_for_status()
        key = str(response.json()["api_key"])

    rows: list[dict[str, Any]] = []
    for task in TASKS:
        got: dict[str, list[dict[str, Any]]] = {"control": [], "treatment": []}
        for repeat in range(REPEATS):
            for arm_name, flag in (("control", False), ("treatment", True)):
                print(f"  {task.name} {arm_name} {repeat + 1}/{REPEATS}", file=sys.stderr)
                got[arm_name].append(await arm(task, with_80085=flag, key=key))

        rows.append(
            {
                "task": task.name,
                "control": median(got["control"]),
                "treatment": median(got["treatment"]),
            }
        )

    RESULTS.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\n{table(rows)}\n")
    print(f"model {MODEL}, median of {REPEATS}. Written to {RESULTS.name}.")
    print(
        "\nAn arm that did not pass verification is not a time -- it is a failure,\n"
        "and no speedup may be quoted from a row containing one."
    )
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))

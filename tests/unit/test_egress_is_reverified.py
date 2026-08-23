"""The egress filter is a fact about the host, not a fact about this process.

The rules are installed with `iptables` on the machine the worker runs on, and
anything on that machine can take them away again: a package upgrade, an
operator running `iptables -F`, a firewall tool rewriting the table, a daemon
restart that drops custom chains. The runtime used to install them once and set
a flag, which meant a worker that survived any of those kept starting networked
containers on an unfiltered bridge -- no error, no log, no way to notice short
of scanning from outside.

So the check is the state. This test is the regression guard for that, and it
needs neither Docker nor iptables: what it pins is that a second run asks the
host again rather than trusting what the first one saw.
"""

from __future__ import annotations

import pytest

from boobs_common.errors import RuntimeUnavailable
from boobs_execution import DockerOciRuntime, docker_oci
from boobs_execution.docker_oci import EGRESS_NETWORK


async def _nothing() -> None:
    """The bridge half, which `tests/security/test_egress.py` covers for real."""


async def test_a_run_after_the_rules_are_flushed_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DockerOciRuntime()
    monkeypatch.setattr(runtime, "_ensure_egress_network", _nothing)
    monkeypatch.setattr(docker_oci.shutil, "which", lambda _: "/sbin/iptables")

    flushed = False

    async def iptables(*args: str) -> int:
        # `-C` answers "that rule is present" while the filter is up. Once the
        # host is flushed the check fails and so does the reinstall, which is
        # what an unprivileged worker or a locked table looks like.
        return 1 if flushed else 0

    monkeypatch.setattr(docker_oci, "_iptables", iptables)

    assert await runtime._egress_network() == EGRESS_NETWORK  # noqa: SLF001

    flushed = True
    with pytest.raises(RuntimeUnavailable, match="refusing to run a networked artifact"):
        await runtime._egress_network()  # noqa: SLF001

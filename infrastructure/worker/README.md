# Running a worker on a host that is not a laptop

Executions only happen while a worker is attached. Recall and recording work
without one; `/v1/ready` reports `queued_executions` so a stalled queue is
visible rather than merely slow.

That makes the worker the one component whose absence stops evidence
accruing — and evidence is the product. A worker on someone's laptop means the
product stops when the lid closes.

This is how to put one somewhere it will not.

## What the host needs

| Requirement | Why |
|---|---|
| **Linux** | The egress filter installs `iptables` rules into `DOCKER-USER` and `INPUT`. Docker Desktop on macOS/Windows runs the daemon in a VM the worker cannot reach, so a networked run is refused there (decision 25). |
| **Docker** | The sandbox. `DECISIONS.md` 10 explains why this cannot be a managed container platform: handing a container the host's Docker socket undoes the isolation the sandbox exists to provide. |
| **`CAP_NET_ADMIN`** | To install the egress rules. Without it a `network: true` run is refused rather than run unfiltered. |
| **Outbound HTTPS** | The worker is an HTTPS client of the API and nothing else. It holds no database or object-storage credential (decision 17). |
| **~2 vCPU, 2 GB** | The default sandbox limits are `SANDBOX_CPU=2`, `SANDBOX_MEMORY_MB=2048`. One worker runs one sandbox at a time. |

A small always-on VM is enough. Capacity is added by adding hosts, not by
making one bigger — executions are leased from Postgres with
`FOR UPDATE SKIP LOCKED`, so nothing coordinates between workers.

> **Not E2B.** The hosted runtime does not enforce an isolated network:
> `allow_internet_access=False` and `deny_out=0.0.0.0/0` were both measured
> leaving outbound TCP open. `E2BRuntime` therefore refuses `network: false`
> artifacts, which is most of them. See `DECISIONS.md` 27 and the per-runtime
> section of `docs/security.md`.

## Standing one up

```bash
# 1. A user that can talk to Docker but owns nothing else.
sudo useradd --system --create-home --home-dir /opt/80085 --shell /usr/sbin/nologin boobs
sudo usermod -aG docker boobs

# 2. The code.
sudo -u boobs git clone https://github.com/charley-forey/80085.git /opt/80085
cd /opt/80085
sudo -u boobs uv sync --frozen

# 3. A key scoped to worker:execute and nothing else. Run this from a machine
#    that already holds the bootstrap token -- not on the worker host, which
#    should never see it.
uv run python scripts/create_worker_key.py --url https://api.80085.ai --token "$BOOBS_BOOTSTRAP_TOKEN"
```

Then write `/etc/80085/worker.env` on the host:

```ini
BOOBS_API_URL=https://api.80085.ai
BOOBS_API_KEY=sk_80085_...          # worker:execute scope only
BOOBS_WORKER_ID=worker-lon-1        # anything stable; it lands in the audit trail
BOOBS_RUNTIME=docker

# Only if artifacts live in an authenticated registry. Both or neither.
BOOBS_REGISTRY_USERNAME=
BOOBS_REGISTRY_PASSWORD=
```

```bash
sudo install -d -m 0700 /etc/80085
sudo chmod 0600 /etc/80085/worker.env
sudo chown root:boobs /etc/80085/worker.env

sudo cp infrastructure/worker/80085-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now 80085-worker
```

If the artifacts are in a private registry, the `boobs` user needs a Docker
login for it too — the runtime pulls as whoever runs it:

```bash
sudo -u boobs docker login <registry> -u <user>
```

## Confirming it actually works

A service that started is not evidence. This is:

```bash
# On the host: it should say worker_started, then nothing but empty leases.
journalctl -u 80085-worker -o cat -f

# From anywhere: queue depth should not climb.
curl -s https://api.80085.ai/v1/ready | jq '.queued_executions'

# End to end -- records an Experience, executes it, checks a verifier proved
# it, and confirms a second organization can recall it by paraphrase.
uv run python scripts/smoke.py --url https://api.80085.ai --token "$BOOBS_BOOTSTRAP_TOKEN"
```

The smoke test is the real check: it is the only one of the three that proves
an execution completed and produced evidence.

## What a leased key can and cannot do

`worker:execute` leases jobs and reports results. It cannot recall, cannot
record, and cannot read another organization's executions. It also cannot
decide whether a run succeeded — the worker reports the raw exit code, stdout
and output bytes, and **the API runs the verifier**. A compromised worker
cannot manufacture evidence, which matters because evidence is the thing being
sold (decision 17).

So a leaked worker key is an availability problem, not an integrity one.
Revoke it and mint another.

## When to add a second

`queued_executions` climbing and not draining. That is the only signal that
means "add a worker"; everything else about the read path scales separately.

Two workers on two hosts need no coordination and no shared state. Two workers
on the *same* host will both lease and both run, which works but halves the
memory each sandbox can safely use — prefer separate hosts.

## The failure that is easy to cause

Do not leave a stray worker running against a database or API you are also
testing against. An orphaned worker leases jobs from whatever it was last
pointed at, and the symptoms show up somewhere else entirely — see
`DECISIONS.md` 8b, which exists because this happened.

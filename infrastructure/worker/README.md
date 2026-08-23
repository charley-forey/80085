# Running a worker on a host that is not a laptop

Executions only happen while a worker is attached. Recall and recording work
without one; `/v1/ready` reports `queued_executions` so a stalled queue is
visible rather than merely slow.

That makes the worker the one component whose absence stops evidence
accruing — and evidence is the product. A worker on someone's laptop means the
product stops when the lid closes.

This is how to put one somewhere it will not.

## The short way

`cloud-init.yaml` in this directory provisions the whole thing on first boot:
Docker from Docker's own repository, an unprivileged `boobs` user in the
docker group, the code, the virtualenv, the unit, enabled and started.

Replace the three `REPLACE_ME` values, paste it into the *user data* box of any
provider that takes one — Hetzner, DigitalOcean, Vultr, Linode, EC2, GCP — pick
an Ubuntu 24.04 image and 2 vCPU / 4 GB, and the worker is leasing by the time
the box finishes booting.

The rest of this file is what that script does and why, for when it does not
work or the host is not fresh.

## What the host needs

| Requirement | Why |
|---|---|
| **Linux** | The egress filter installs `iptables` rules into `DOCKER-USER` and `INPUT`. Docker Desktop on macOS/Windows runs the daemon in a VM the worker cannot reach, so a networked run is refused there (decision 25). |
| **Docker** | The sandbox. `DECISIONS.md` 10 explains why this cannot be a managed container platform: handing a container the host's Docker socket undoes the isolation the sandbox exists to provide. |
| **`CAP_NET_ADMIN`** | To install the egress rules. Without it a `network: true` run is refused rather than run unfiltered. |
| **Outbound HTTPS** | The worker is an HTTPS client of the API and nothing else. It holds no database or object-storage credential (decision 17). |
| **~2 vCPU, 4 GB** | The default sandbox limits are `SANDBOX_CPU=2`, `SANDBOX_MEMORY_MB=2048`, and the daemon needs room beside them. One worker runs one sandbox at a time. |
| **x86, not ARM** | Every capability image is `linux/amd64` and every Experience declares `architecture: amd64`, which is a hard filter in recall. An ARM host would emulate every sandbox, and the cheap tier at most providers is ARM -- so this is the requirement that costs money. |

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
# Not straight into /opt/80085: useradd --create-home has already put skel
# files there, and git refuses a non-empty target.
git clone --depth 1 https://github.com/charley-forey/80085.git /tmp/80085src
sudo cp -a /tmp/80085src/. /opt/80085/ && sudo rm -rf /tmp/80085src
sudo chown -R boobs:boobs /opt/80085
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
login **as well as** the two variables above. The variables let the E2B runtime
authenticate a template build; this login is what lets the local Docker daemon
pull, and the runtime pulls as whoever runs it — so a login as `root` does not
help a service running as `boobs`:

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

## Scaling this, in the order it actually matters

Execution is the expensive half of the system and the only part that needs
machines added to it. Four things, cheapest first — and the order is the point,
because three of them are free and the fourth is the one people reach for.

**1. Most executions should never happen.** Artifacts are pinned by digest, so
the same artifact and the same inputs deterministically produce the same
output. `CachingRuntime` already exists behind the `ExecutionRuntime` protocol
(`BOOBS_EXEC_CACHE=1`, off by default). It is off because a replayed result
must not be recorded as a fresh independent verification — that would inflate
the one number this product sells. Finishing that (decision 20 names exactly
what is missing) removes more load than any number of hosts.

**2. Recall volume is not execution volume.** An agent recalls, reads the
evidence, and runs the artifact in its own environment. The platform executes
to *generate evidence*, and evidence saturates: `usage_score` is log-scaled and
runs are capped per organization before they reach Wilson, so the fiftieth
verified run of a capability is worth almost nothing and the five-thousandth is
worth literally nothing. Execution is a sampling problem with a ceiling. Recall
is the surface that scales with the world, and it is a read served by two
indexes.

**3. Add hosts, not size.** A worker runs one sandbox at a time, and leases are
claimed with `SELECT ... FOR UPDATE SKIP LOCKED`. That means N workers need no
leader, no sharding, no partitioning and no coordination whatsoever — a second
host is capacity with no design change. Autoscale on `queued_executions` from
`/v1/ready`, never on CPU: a worker waiting on a container looks idle.

**4. Only then, a different runtime.** The `ExecutionRuntime` protocol is one
swappable class, so this is a routing decision rather than a rewrite. Note what
the choice is actually between: E2B was tried and refuses `network: false`
artifacts because it does not enforce an isolated network (decision 27), so the
useful direction is not "hosted" but *stronger local isolation* —
gVisor (`runsc`) as Docker's runtime is a `daemon.json` change and retires the
"Docker is not a boundary against a kernel exploit" gap in `docs/security.md`.

**What does not need solving yet.** Multi-region, sharding and read replicas
are all still deferred and should stay that way: one Postgres is nowhere near
saturated, and each of those adds a failure mode someone then has to debug at
3am. `docs/scaling.md` is the honest account of what breaks first.

## The failure that is easy to cause

Do not leave a stray worker running against a database or API you are also
testing against. An orphaned worker leases jobs from whatever it was last
pointed at, and the symptoms show up somewhere else entirely — see
`DECISIONS.md` 8b, which exists because this happened.

# Security model

> Treat every artifact as hostile code that wants your credentials, your
> network, and your host.

That is not a posture, it is the accurate description of what a public
registry of executable artifacts is.

## The boundary

```
API process              WORKER process             SANDBOX container
──────────────           ──────────────             ─────────────────
reads, ranks,            talks to the               runs untrusted code
records, enqueues        container runtime          with nothing
                                                    it can reach
never executes           never runs artifact
artifact code            code in-process
```

The API is exposed publicly and holds database credentials, so it must never
execute an artifact. The worker holds the dangerous capability and lives in
one file: `packages/execution/src/boobs_execution/docker_oci.py`.

## What every execution gets

| Control | Flag | Stops |
|---|---|---|
| No network | `--network none` | exfiltration, SSRF, C2, mining pools |
| Filtered egress | dedicated bridge + `DROP` rules | metadata theft, LAN scanning, host services |
| Read-only root | `--read-only` | persistence, tampering with the image |
| Non-root | `--user 65534:65534` | most privilege escalation |
| No capabilities | `--cap-drop ALL` | raw sockets, mounts, ptrace |
| No new privileges | `--security-opt no-new-privileges` | setuid escalation |
| CPU cap | `--cpus` | cryptomining, noisy neighbours |
| Memory cap | `--memory` + `--memory-swap` equal | OOM of the host, swap thrash |
| PID cap | `--pids-limit` | fork bombs |
| Sized `/tmp` | `--tmpfs /tmp:size=…,noexec,nosuid` | disk exhaustion, temp-file exec |
| Wall clock | timeout, then `docker kill` | infinite loops |
| Output cap | truncation on stdout/stderr and files | log-flood denial of service |
| No mounts | inputs and outputs via `docker cp` | host filesystem access |
| No socket | never mounted | container escape to the daemon |
| No ambient env | only explicitly passed variables | credential theft |

Limits come from a policy object (`SANDBOX_*`), not from constants. They are
defaults, not universal truths.

## Egress, when an Experience asks for the network

`constraints.network` is set by the artifact's own author, and nothing
approves it. `--network=bridge` would therefore be an attacker-chosen flag
that reaches the cloud metadata service, the worker's LAN, and every service
bound on the worker itself. Ranking penalises such an Experience; it does not
stop it running.

So a networked run does not join the default bridge. It joins `80085-egress`,
a dedicated Docker network on the `br-80085egress` interface, and the worker
installs `DROP` rules for that interface in two chains:

* **`DOCKER-USER`** -- forwarded traffic: the metadata service, other
  containers, the LAN, the internet.
* **`INPUT`** -- traffic addressed to the worker itself, which is delivered
  locally and never reaches `FORWARD`. Filtering only `DOCKER-USER` would
  leave every service on the worker reachable from inside the sandbox.

Dropped whatever the flag says: `169.254.0.0/16` (including
`169.254.169.254`), `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`, `100.64.0.0/10`, `192.0.0.0/24`, `198.18.0.0/15`,
`224.0.0.0/4`, `240.0.0.0/4`. Public DNS and public HTTP still work, which is
the point: this is a deny-list on the private world, not an allowlist of
destinations.

**It fails closed.** No `iptables`, no privileges, no `DOCKER-USER` chain, or
a network already on some other interface -- and the networked run is refused
with the exact commands an operator needs to install the rules by hand. A
control that switches itself off when it cannot run is not a control. Runs
with `network: false` are unaffected and need none of this.

What it does **not** stop: which *public* hosts are reachable (spec section
17's per-domain allowlist is still unbuilt), exfiltration through DNS to a
public resolver, or a kernel-level bypass. It is IPv4 only -- the network is
created without IPv6 -- so enabling IPv6 on it would open a hole the rules do
not cover.

## Tiered execution

`SANDBOX_TIMEOUT_SECONDS` is one number for everybody, and raising it to make
real agent workflows possible would hand every anonymous stranger an hour of
networked compute per request. Length is a tier instead:

| Tier | Wall clock | Who gets it |
|---|---|---|
| `quick` | today's `SANDBOX_TIMEOUT_SECONDS` (60s) | everyone; the default |
| `standard` | 10 minutes | organizations with a `policies` grant |
| `extended` | 1 hour | a grant **and** a verifier that checks output |

`extended` needs more than approval because `exit_code` -- the floor verifier
-- passes for an artifact that mines for an hour and exits 0. Only verifiers
that look at what the run produced (`json_schema`, `sha256`) qualify.

An author asks by declaring `constraints.max_duration_seconds`; the smallest
tier that covers it is recorded on the version. The **lease** decides what
that request is worth, against `policies` rows that no endpoint writes, and an
unapproved request is downgraded to `quick` rather than refused. The API sends
a tier *name*, never a number of seconds, and the worker looks up locally what
that name is worth.

**Only the wall clock moves.** `cpu`, `memory_mb`, `tmpfs_mb` and `pids` are
Docker cgroup flags with no E2B equivalent, so tiering them would be a promise
one of the two runtimes silently breaks. Wall clock is enforced by both.

## Why `docker cp` instead of a bind mount

A bind mount is the ordinary way to get files into a container, and it is a
hole in exactly the wall this system needs. `docker create` → `docker cp` in →
`start` → `docker cp` out moves bytes without ever giving the container a path
into the host filesystem.

`/work` is an anonymous volume rather than a tmpfs, because `docker cp` into a
stopped container writes into the image layer, which a tmpfs would then shadow
at start. **Known ceiling:** tmpfs size limits therefore do not bound `/work`.
See `DECISIONS.md` §9 for the upgrade path.

## Why digests, never tags

A tag is a mutable pointer. If an artifact could be referenced by tag, then:

* evidence collected for version 4 would describe bytes that no longer exist;
* a compromised publisher could silently swap a verified capability for a
  malicious one, and every success rate in the system would keep vouching for
  it.

So a tag is refused twice — at the API boundary
(`ArtifactRepository.register`) and again inside the runtime before anything
is pulled. Both refusals are tested.

## Tenancy

One function decides who can see what: `visible_to` in
`packages/security/src/boobs_security/policy.py`, mirrored as a SQL predicate
in `visibility_clause`.

* `private` — the agent that created it
* `organization` — any agent in the owning organization
* `public` — everyone, which is what makes cross-agent reuse possible

Using someone's public Experience is allowed; *mutating* it is not. An
execution is never cross-tenant readable — it is the caller's own run and may
contain the caller's data, so another organization gets `404`, not `403`.

## Keys

SHA-256 hashed at rest, scoped, revocable, and stamped with `last_used_at` on
every request. The plaintext exists exactly once, in the response that created
it. A database dump yields no working credentials.

## Testing this

`tests/security/` attacks the sandbox with real containers and real payloads:
network access, DNS, read-only rootfs, uid, `setuid(0)`, daemon socket,
writable mounts, wall clock, fork bomb, memory hog, output flood, output size,
and -- with `network: true` -- the metadata service, the link-local range, the
host's own gateway, and a real listener on a real RFC1918 address.

**If one of these fails, fix the sandbox. Never relax the test.**

## Isolation is per-runtime, and E2B does not enforce the network

The table above describes `DockerOciRuntime`, which is what `BOOBS_RUNTIME`
selects by default. It is not a description of every runtime.

**E2B does not enforce an isolated network.** Measured against the live
service: with `allow_internet_access=False`, and again with
`network={"deny_out": ["0.0.0.0/0"]}`, a sandbox still opened a TCP connection
to `1.1.1.1:53`. Only DNS is refused, which is what let this go unnoticed -- a
resolver failure reads as "no network" until something dials an address
directly, which is what exfiltrating code does.

So `E2BRuntime` **refuses** any execution with `network: false` rather than
serving it unsafely, and says to use the Docker runtime instead. E2B is still
appropriate for artifacts that declare network access, where no isolation was
promised in the first place.

Four Docker limits also have no E2B equivalent and are not enforced there:
`cpu`, `memory_mb`, `tmpfs_mb` and `pids`. The wall clock is enforced on both.

The lesson generalises: isolation is not one property. A Firecracker microVM is
a stronger boundary than a shared kernel against a kernel exploit, and a weaker
one here. Check the specific control you depend on, on the specific runtime you
run.

## Known gaps

* **Docker is not a security boundary against a kernel exploit.** It is
  adequate for controlled use. For genuinely arbitrary public code, run
  `BOOBS_RUNTIME=e2b`: `E2BRuntime` puts each run in a Firecracker microVM, so
  a guest kernel exploit costs the attacker a disposable VM rather than the
  worker's host. It is not the default because it needs an `E2B_API_KEY` and
  bills per second, not because Docker is safer.
* **The E2B runtime enforces fewer of the limits it is handed.** `cpu`,
  `memory_mb`, `tmpfs_mb` and `pids` are Docker cgroup flags with no direct
  E2B equivalent; the microVM's own shape bounds the run instead. Wall clock,
  network reachability, output size and digest pinning are enforced in both.
* **No image signing or SBOM yet.** Digest pinning proves the bytes did not
  change; it does not prove who produced them.
* **No egress allowlist.** Link-local, metadata, loopback and RFC1918 are now
  dropped for every networked run (see above), but the *public* internet is
  still all-or-nothing: an artifact granted the network can talk to any public
  address, and DNS to a public resolver is a working exfiltration channel.
  Spec §17 describes per-domain policy; the field is in the schema, the
  enforcement is not built.
* **Egress filtering needs a Linux Docker host and `CAP_NET_ADMIN`.** The
  worker shells out to `iptables`. On Docker Desktop, an unprivileged worker,
  or a remote daemon it cannot install the rules -- and refuses the networked
  run instead of running it unfiltered. `E2BRuntime` has no egress filter at
  all: `allow_internet_access` is a boolean with no destination policy. Its
  mitigation is topology, not policy -- the microVM is in E2B's cloud, so the
  private network it can reach is not the worker's.
* **`/work` is not disk-quota bounded** (see above). Neither obvious fix works
  on a stock Docker host: a tmpfs-backed local volume is unmounted between
  `docker cp` and `start` and loses the inputs, and `--storage-opt size=`
  needs devicemapper, btrfs, zfs or xfs project quotas rather than overlay2.
  The only bound is the wall clock, which is one more reason the longer
  execution tiers are granted by an operator rather than self-serve.

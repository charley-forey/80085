# Standing up the scheduler

Nothing in this repository runs on a clock. Railway does. This is how to make
the service that calls `80085-scheduler`, and how to tell whether it ran.

Jobs are named, invoked one per process, and exit:

```bash
uv run 80085-scheduler retention     # drop recall misses older than 90 days
```

There is one job today. Each job gets **its own Railway service** with its own
schedule; they share the image and nothing else.

## The service

| Setting | Value |
|---|---|
| Name | `scheduler-retention` |
| Source | this repository, same branch as `api` |
| Root directory | *(empty — the Dockerfile is repo-relative)* |
| Builder | Dockerfile, `infrastructure/docker/Dockerfile` |
| Custom start command | `80085-scheduler retention` |
| Cron schedule | `17 3 * * *` |
| Healthcheck | **none** — leave the path empty |
| Restart policy | `Never` |
| Pre-deploy command | **none** — leave it empty |

`17 3 * * *` is daily at 03:17 UTC. Retention is a 90-day window; the exact
minute is worth nothing and an off-the-hour minute keeps it out of the crowd
that every other system on the internet schedules at `0 3 * * *`.

Three of those rows are the ones people get wrong:

* **No healthcheck.** A cron service exits. A healthcheck path makes Railway
  wait for an HTTP response that never comes and then fail the deployment.
* **Restart `Never`.** `ON_FAILURE` would retry a failed job immediately and
  keep retrying, which for a job that fails because Postgres is down is a
  tight loop against a database that is down. The next tick is the retry.
* **No pre-deploy command.** `api` runs `alembic upgrade head`; this service
  must not. Two services racing the same migration is the one way to get a
  half-applied schema, and `api` already owns it.

## Can `railway.json` express the schedule? No — not for this service.

The Config-as-Code schema does have `deploy.cronSchedule`, so the answer used
to be yes. It is now no, for a reason that has nothing to do with cron:
**Config as Code is deprecated and new services cannot opt into it**
(existing files stop being read on 2026-12-01). `infrastructure/railway/railway.json`
still configures `api` because `api` is a legacy service that already used it.
A service created today cannot.

So the schedule is set **in the dashboard**: the service's Settings page, the
"Cron Schedule" field, then save. The alternative is Railway's Infrastructure
as Code (`.railway/railway.ts`), which is the current replacement — but it
refuses to manage a project while any service is still on `railway.json`, so
adopting it means migrating `api` off Config as Code first. That is a separate
change with its own blast radius, and it is not required to get retention
running.

**Do not provision this from a checkout.** It costs money on somebody's
account and it is a live-infrastructure decision. This file is the request.

## Variables

Exactly one, and it is the same one `api` has:

```
DATABASE_URL   ${{Postgres.DATABASE_URL}}
```

Nothing else. No `BOOBS_BOOTSTRAP_TOKEN`, no S3 credentials, no API key — the
scheduler mints nothing, stores nothing and calls nothing. If a future job
needs object storage it can be given `S3_*` then, on that job's own service.

`OTEL_EXPORTER_OTLP_ENDPOINT` if you want the job's spans where the API's are;
it is optional and off by default.

## Confirming it ran

A created service is not evidence. In order of how much they prove:

```bash
# 1. It ran at all, and what it did. One line per run.
railway logs --service scheduler-retention | grep job_finished
# {"event": "job_finished", "job": "retention", "affected": 0, ...}
```

`affected: 0` is the normal steady state — the window is 90 days and the job
runs daily, so most days delete nothing.

```bash
# 2. It is not silently skipping. Railway skips a tick whose predecessor is
#    still Active, so a deployment stuck in Active is a schedule that stopped.
railway status --service scheduler-retention
```

Every run should be `Completed`, never `Active` between ticks and never
`Crashed`. A crashed deployment is the alarm: the process exits `1` when a job
raises and `2` when the start command names a job that does not exist — the
second is what a typo in "Custom start command" looks like, and it will crash
identically on every tick until someone fixes it.

```bash
# 3. It is actually load-bearing. Grep the *api* logs for the fallback.
railway logs --service api | grep recall_miss_retention_swept_on_write
```

This should return nothing. Until the cron exists, the API still sweeps
retention on the miss-write path, and it logs a warning **whenever that sweep
actually deletes something**. With the job running there is never anything left
for it to delete — so a line here means the schedule is not doing its work,
whatever the dashboard says.

## Then, and only then, turn the fallback off

Once `job_finished` has appeared on consecutive days and the warning above has
not, set on the **`api`** service:

```
BOOBS_MISS_SWEEP_ON_WRITE=0
```

That takes the delete out of the recall-miss write path for good. It is
deliberately the last step and deliberately manual: with it unset the worst
case is a redundant indexed range delete that matches nothing, and with it set
too early the worst case is retention that stopped without saying so.

## Adding the next job

Staleness sweeps (spec §24) and re-verification (§26–27) are the named next
two. Each is: a coroutine in `apps/api/src/boobs_api/scheduler.py`, a line in
`JOBS`, and a second Railway service with the same settings as the table above
and a different start command and schedule. Nothing here is per-job except the
name.

---
title: Self-Hosting & Deployment
description: Running LensWord for other people — managed Postgres, TLS, secrets, and backups.
---

# Hosted deployment

Running LensWord as a service for other people, on managed infrastructure. This
is distinct from the Docker Compose instructions in
[Getting Started](/setup/), which run everything on one host
including its database — fine for a single user, wrong for a service.

## Read this first

**Notification delivery is only partly real.** Desktop notifications work end
to end in principle — the backend queues them and the shell raises a native
toast — but *no toast has been observed on any operating system*, because that
needs a signed packaged build (ROADMAP 3.1, issue #65). **Push and email have
no provider at all** and only write to the application log.

If you host this for other people, they will set reminders and, unless they use
the desktop shell, receive nothing. Say so on your sign-up page. The
application itself is honest about it — the settings screen does not pretend to
send — and a deployment should not undo that.

AI features are off unless you configure them, and are local-only (Ollama). No
data leaves your infrastructure by default.

## What has to change from the Compose stack

| | Compose | Hosted |
| --- | --- | --- |
| Database | container beside the app | managed Postgres, backed up |
| Secrets | `.env` on the host | the platform's secret store |
| TLS | none | terminated at a load balancer or proxy |
| Instances | one | more than one, behind a balancer |
| Migrations | on boot, every instance | on boot is still correct — see below |

## Database

Provision managed Postgres and point the backend at it:

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/lensword
```

The `+psycopg` suffix is required. Without it SQLAlchemy looks for `psycopg2`,
which this project does not depend on, and fails at import rather than at
connect.

**Require TLS.** Most managed providers accept it as a query parameter:

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/lensword?sslmode=require
```

### Connection budget

`DB_POOL_SIZE` (default 5) and `DB_MAX_OVERFLOW` (default 10) bound each
instance's pool. The number that matters against a plan's connection cap is
their **sum multiplied by the instance count** — four instances on the defaults
is 60 connections, which exceeds several entry-level plans on its own. Size the
pool to the plan, not to the instance.

Connections are pre-pinged and recycled after 280 seconds, below the five-minute
idle cutoff common to managed Postgres and to poolers, so a connection dropped
underneath the pool is replaced rather than handed to a request.

### Migrations

The backend runs `alembic upgrade head` on boot. That stays correct with
several instances — Alembic takes a lock, so the losers wait rather than
racing — but it means **a deploy that starts instances before the migration
finishes will have them block, not fail**. Allow for it in your health-check
grace period.

Migrations are additive in this project's history so far, but nothing enforces
that. Take a backup before deploying one you have not read.

**The 15-revision batch `20260730_05` through `20260730_19` has now been run
against a populated database once** (issue #165), closing the gap where every
prior run had only ever touched a database the test suite created moments
earlier. Method and results, so the next batch can be checked the same way:

A throwaway Postgres 18.3 (Homebrew) cluster on a non-default port stood in
for the managed instance — **not** the postgres:17 CI runs, so treat the
numbers below as indicative rather than a CI-equivalent result. The database
was brought to `20260730_04` (the revision immediately before this batch) and
seeded through the application's real use cases and repositories — not SQL —
with 5 accounts, 3,100 words, 620 review attempts, 100 room placements, 5
rooms, 5 reminders and 31 review sessions. Three of the five accounts were
left with no `recall_settings` row at all (the "never opened the settings
screen" case `20260730_14` exists for); one had already saved an explicit
`fsrs` preference and one an explicit `sm2`, to check the migration leaves a
deliberate choice alone.

One wrinkle in the method is itself worth recording: `20260730_01`'s baseline
migration calls `Base.metadata.create_all()` against whatever `models.py`
the checked-out code has, so a brand-new database built with today's code
gets the *current* full schema at revision `20260730_01` — every later
revision through `20260730_19` then finds its table or column already
present and skips it (see `test_alembic_baseline.py`). Stopping the alembic
stamp at `20260730_04` is not enough on its own to reproduce a pre-batch
database; the tables and columns this batch adds had to be dropped by hand
afterward to get a schema shape a real `20260730_04`-era account would
actually have had. Practically, this means the incremental `CREATE
TABLE`/`ADD COLUMN` bodies in `20260730_02` onward are dead code on every
fresh install and only run for real on a genuine legacy adoption — which is
what this test reconstructed.

**Timing.** An isolated `alembic upgrade head` from `20260730_04` to
`20260730_19` against the seeded database took **0.67s** wall-clock. A second
run instrumented with a concurrent polling loop against `pg_stat_activity`
(to watch for locks) took 2.81s — the difference is polling overhead (roughly
70 forked `psql` processes), not the migrations, which do the same work
either way.

**Locks.** No row with `wait_event_type = 'Lock'` appeared in ~70 samples of
`pg_stat_activity` taken during the run. Nothing in this batch holds a lock
long enough to be caught at this data volume; that says nothing about an
account with an order of magnitude more words.

**Data survival.** Every pre-existing row count was unchanged after the
upgrade: 3,100 words, 620 review attempts, 100 room placements, 5 rooms, 5
reminders, 5 users. `recall_settings` went from 2 rows to 5: the three
accounts with none got an inserted `sm2` row, the account that had already
chosen `fsrs` kept it, and the account that had already chosen `sm2` was
untouched — exactly `20260730_14`'s documented intent, confirmed against real
rows rather than a fresh test database where every account already has (or
lacks) settings for reasons unrelated to migration order.

**The application boots against the migrated database** with
`AI_PROVIDER=none` and serves real requests against the seeded accounts: a
review session (start, answer, complete) updated a word's `review_state`; the
weaknesses endpoint queried the new `mistake_events` table (empty, since the
seed script recorded no mistakes, but the query executed); a learning path
generation request correctly reported `status: "disabled"` with AI off
rather than erroring; starting a conversation and starting a role-play
scenario attempt both wrote rows to `conversation_sessions` and
`scenario_attempts` respectively.

**Downgrade.** `alembic downgrade 20260730_14` on a copy of the migrated
database completed in 0.47s, dropped the 7 tables that `20260730_15` through
`20260730_19` added, and left every row in the surviving tables intact —
including the `recall_settings` rows `20260730_14` inserted, which its
`downgrade()` deliberately does not remove (removing them would discard real
preferences to undo a default change, per the migration's own comment). One
consequence worth knowing: **you cannot actually run this application
against that downgraded schema.** Startup calls `init_db()` unconditionally,
which runs `alembic upgrade head` before the app serves a single request — so
pointing a fresh process at the downgraded copy silently upgraded it straight
back to head before the first login attempt. A downgrade only "sticks" for as
long as no instance of the application boots against that database.

**Interrupting the upgrade** — `kill -9` on the alembic process 50-150ms into
a chain that takes roughly that long end to end, tried twice on two separate
copies — left the database exactly at `20260730_04` both times: no partial
tables, no stray columns, `alembic_version` unmoved, and no orphaned
connections or locks in `pg_stat_activity`. This is not luck: `alembic/env.py`
wraps every pending revision for one `upgrade` invocation in a single
`context.begin_transaction()`, and Postgres's transactional DDL means a
killed client's uncommitted work is discarded wholesale rather than left
half-applied. Simply re-running `alembic upgrade head` afterward reached head
normally with no manual reconciliation. **No recovery procedure beyond "run
it again" is needed on Postgres** — but this guarantee is specific to a
dialect with transactional DDL and to a single-transaction `env.py`; treat it
as re-verified if either changes.

Not tested: a seed volume large enough to make locking or downgrade duration
actually matter (tens of thousands of words rather than thousands), a
concurrent write load during the upgrade, and behavior on postgres:17 itself
rather than 18.3.

## Secrets

Use the platform's secret store, not an `.env` file baked into an image.

| Variable | Notes |
| --- | --- |
| `SECRET_KEY` | Signs every access token. Rotating it logs everyone out, which is the correct response to a suspected leak. |
| `DATABASE_URL` | Contains the database password. |
| `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` | Only read on first boot. Unset them afterwards. |

Generate a real `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

The default value in `.env.example` is a placeholder and the application ships
with an obviously-fake one. Neither is safe, and neither is checked for at
startup — that is a gap worth knowing about rather than one this document can
paper over.

## TLS and origins

Terminate TLS at your load balancer or reverse proxy; the backend speaks plain
HTTP and should not be exposed directly.

`CORS_ORIGINS` must list the exact origins the frontend is served from —
scheme, host and port. It is a JSON array:

```
CORS_ORIGINS=["https://lensword.example.com"]
```

The desktop shell is a separate consideration: it validates its endpoint and
**refuses plain HTTP to a remote host** (ADR 0001), so a hosted deployment must
serve HTTPS or the shell will not talk to it at all.

## Running more than one instance

Safe as of ROADMAP 4.2. Jobs persist in the database rather than in process
memory, and each firing is claimed through a unique constraint, so concurrent
instances deliver a reminder once rather than once each.

Two consequences worth planning for:

- Every instance polls the shared job store, so instance count multiplies
  scheduler database traffic as well as request traffic.
- A crash between claiming a firing and delivering it **loses** that
  notification rather than duplicating it. That trade is deliberate — a missed
  nudge beats a double one — but it is untested under real process failure.

## Rate limiting

Four budgets, each per account except login (per IP, since there is no
account yet): auth attempts, AI generations, outbound URL fetches, uploads.
Defaults and `.env` variable names are in `.env.example`; a 429 carries
`Retry-After`.

**Enforced in-process, per instance.** The limiter is a dict living in one
backend process — correct and sufficient for the single-instance Compose
deployment this project ships by default, but **not enforced across
instances**. Behind a load balancer with N instances, a caller distributed
across all of them can reach up to N times the configured budget before any
single instance's counter trips, for the same reason the scheduler needed a
database-backed claim (see "Running more than one instance" above) rather
than in-memory state — the difference is that half of that fix has not been
built here. There is no shared-state store (Redis or otherwise) anywhere in
this project yet; adding rate limiting that holds under N instances means
adding one.

Size the per-instance defaults down if you run more than one instance and
want the aggregate ceiling to stay close to what the numbers in
`.env.example` suggest, and do not treat this as a defense against a
distributed attacker until it is instance-count-aware.

## Outbound network access

The URL import on the Extract page makes the **server** fetch a page the user
chose. That is a server-side request forgery surface by construction, and the
application guards it: only `http`/`https` on ports 80 and 443, no embedded
credentials, every resolved address checked against private, loopback,
link-local and reserved space, and every redirect hop re-validated as if it had
been typed. `169.254.169.254` — the cloud metadata endpoint that hands out
instance credentials — is refused along with the rest of link-local space.

One gap remains and cannot be closed in application code alone. Between
resolving a hostname and connecting to it, DNS can return a different answer
(**DNS rebinding**). Pinning the connection to the address that was validated
would break TLS certificate validation for the hostname, so the guard checks
what it resolves and connects by name.

**Restrict egress from the application container.** Denying it outbound access
to your own private ranges and to the metadata endpoint closes the rebinding
gap and makes the application-level checks a second line rather than the only
one. If your platform does not offer egress rules, treat the URL import as a
feature to leave unused rather than one to rely on.

## Backups

Nothing in this repository backs anything up. Use the provider's automated
backups and confirm you can restore from one *before* you need to; a backup
nobody has restored is a hypothesis.

The `lensword_data` volume holds the AI settings override file. It is small and
regenerable from the admin screen, so the database is the thing that matters.

## What this document does not cover

- **Horizontal scaling of the frontend** — it is static files; serve them from
  anything.
- **WAF, DDoS protection** — not implemented in the application. Rate limiting
  is (see above), but only per instance — it is not a substitute for either of
  these behind a load balancer with more than one instance.
- **Log aggregation and alerting** — the application logs to stdout at
  `LOG_LEVEL`; collecting that is your platform's job.
- **Multi-tenancy beyond per-account isolation** — every query is scoped by
  account (audited in ROADMAP 4.1, zero findings), but there is no notion of an
  organisation or shared deck.
- **A tested deployment on any specific provider.** Nothing here has been run
  on RDS, Cloud SQL, Neon, Fly, Railway or anything else. This documents what
  the application requires; it is not a recipe anyone has followed end to end.

# Hosted deployment

Running LensWord as a service for other people, on managed infrastructure. This
is distinct from the Docker Compose instructions in the
[README](../README.md#docker-recommended), which run everything on one host
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

## Backups

Nothing in this repository backs anything up. Use the provider's automated
backups and confirm you can restore from one *before* you need to; a backup
nobody has restored is a hypothesis.

The `lensword_data` volume holds the AI settings override file. It is small and
regenerable from the admin screen, so the database is the thing that matters.

## What this document does not cover

- **Horizontal scaling of the frontend** — it is static files; serve them from
  anything.
- **Rate limiting, WAF, DDoS** — none is implemented in the application.
- **Log aggregation and alerting** — the application logs to stdout at
  `LOG_LEVEL`; collecting that is your platform's job.
- **Multi-tenancy beyond per-account isolation** — every query is scoped by
  account (audited in ROADMAP 4.1, zero findings), but there is no notion of an
  organisation or shared deck.
- **A tested deployment on any specific provider.** Nothing here has been run
  on RDS, Cloud SQL, Neon, Fly, Railway or anything else. This documents what
  the application requires; it is not a recipe anyone has followed end to end.

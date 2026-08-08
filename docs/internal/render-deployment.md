# Render.com deployment (free alternative to Cloudflare Containers)

Maintainer/ops reference, not part of the published docs site
(`srcExclude: ['internal/**']`). Companion to
[cloudflare-deployment.md](./cloudflare-deployment.md) — read that first
for *why* a plain Cloudflare Worker can't run `apps/backend`/`apps/mcp` as
they exist today (real Python processes, native Postgres driver). This
page exists because Cloudflare Containers specifically requires the
**Workers Paid plan ($5/mo minimum)** — confirmed by an actual
"Unauthorized" failure attempting to deploy against a Free-plan account,
not assumed from pricing docs alone. Render's Free plan needs no card on
file at all.

## The trade-off

A Free Render web service spins down after 15 minutes with no inbound
traffic; the next request pays a ~30-50s cold start while it wakes back
up. Fine for early-stage/low-traffic use, not for "always instantly
responsive." Upgrading a single Render service off Free later removes
this without touching anything else here or in the app itself.

## Setup (recommended path: the dashboard, not `render.yaml` blindly)

`render.yaml` at the repo root is a Blueprint — infrastructure-as-code,
confirmed field-by-field against
[render.com/docs/blueprint-spec](https://render.com/docs/blueprint-spec)
but **not** dry-run validated against a live account (unlike the
Cloudflare `wrangler.toml` files, there's no local Render CLI equivalent
to `wrangler deploy --dry-run` available here). The safer first attempt:

1. Render Dashboard → **New → Web Service** → connect this GitHub repo.
2. **Runtime: Docker**, **Dockerfile path**: `apps/backend/Dockerfile`,
   **Docker build context**: `apps/backend`.
3. **Plan: Free**.
4. **Environment variables** — set these (see
   `apps/backend/.env.example` for what each one does):
   - `ENVIRONMENT=production`
   - `DATABASE_URL` — **your Supabase project's *Session pooler* connection
     string** (port `5432`, host `aws-0-<region>.pooler.supabase.com`) —
     not Direct connection (IPv6-only, unreachable from Render) and not
     Transaction pooler (port `6543`). See "Supabase-specific: which
     connection string" below for why.
   - `SECRET_KEY` — generate with `openssl rand -hex 32`, or let Render's
     "Generate" button do it.
   - `CORS_ORIGINS=["https://lensword.conectlens.com","https://lensword-frontend.pages.dev"]`
   - `AI_PROVIDER=none` (a Render web service cannot run its own Ollama
     daemon, so `ollama` doesn't work here — `gemini`, `vertex`, or
     `openai` do; see
     [docs/install/cloud-ai-providers.md](../install/cloud-ai-providers.md)
     for the field each one needs)
   - `REMOTE_MCP_ENABLED=false`
5. Deploy. Render auto-builds `apps/backend/Dockerfile` and redeploys on
   every push to `main` by default (no separate GitHub Actions workflow
   needed for this — Render's own GitHub integration watches the branch).
6. Repeat for `apps/mcp` (Dockerfile: `apps/mcp/Dockerfile`, context:
   `apps/mcp`), with:
   - `LENSWORD_MCP_TRANSPORT=http`
   - `LENSWORD_MCP_REMOTE_ENABLED=1`
   - `LENSWORD_API_URL` — the backend service's real Render URL from step 5
     (`https://<whatever-render-actually-named-it>.onrender.com`)
   - `LENSWORD_MCP_WORKSPACE=production`

Once both are confirmed working, `render.yaml` lets you reproduce this
from scratch (`render blueprint launch` from the Render CLI, or the
Dashboard's "New from Blueprint" pointed at this repo) — update its
`DATABASE_URL`/`LENSWORD_API_URL` values to match what you actually used
if they differ from the placeholders in the file.

## Automatic migrations — already wired, nothing extra needed

`apps/backend/Dockerfile`'s `CMD` already runs `alembic upgrade head`
before starting `uvicorn`, on **every** container start — this was built
for the Docker Compose deployment target and applies unchanged to
Render or any other Docker host. Point `DATABASE_URL` at Supabase and
migrations run automatically on every deploy; no separate migration step
or workflow is needed.

## Supabase-specific: which connection string

**Use the Session pooler string, not the Direct connection string.** This
page originally recommended Direct connection (reasoning below is still
correct on its own terms — it's just beaten by a bigger, unrelated
problem). Confirmed wrong by a real Render deploy failure:

```
psycopg.OperationalError: connection is bad: connection to server at
"2406:da12:557:f800:...", port 5432 failed: Network is unreachable
```

Supabase's Direct connection hostname (`db.<ref>.supabase.co`) resolves to
an **IPv6-only** address for most projects today (Supabase dropped the
free IPv4 address for new/existing direct-connection hosts; it's a paid
add-on now). Render's network — at least on the plans used here — has no
IPv6 egress, so the connection never leaves the container. This has
nothing to do with pgbouncer/prepared-statement behavior; it's a plain
network-reachability failure, and it happens before any query runs (this
is why it surfaced inside Alembic's very first `connectable.connect()`
call, not as an app-level error).

Supabase gives you three connection strings for the same database
(Database settings page in the dashboard):

- **Direct connection** (port `5432`, host `db.<ref>.supabase.co`) — IPv6
  only on most projects now. Don't use this from Render.
- **Session pooler** (port `5432`, host
  `aws-0-<region>.pooler.supabase.com`) — Supavisor in session mode: each
  client holds a dedicated server-side connection for the life of the
  session, so it behaves like a direct connection for everything
  SQLAlchemy/Alembic need (prepared statements, `SET`, etc.), and it's
  **IPv4-compatible**. This is the one to use here.
- **Transaction pooler** (port `6543`, same pooler host) — connections are
  handed back to the pool between transactions, so server-side prepared
  statements and some session-level operations don't work reliably.
  Avoid for this app regardless of the IPv4/IPv6 question.

This app already does its own connection pooling in-process
(`DB_POOL_SIZE`/`DB_MAX_OVERFLOW` in `apps/backend/.env.example`) and runs
as a persistent container, so Session pooler's per-client dedicated
connection isn't wasted the way it would be for a serverless function —
it's just the IPv4-reachable equivalent of Direct connection. Copy the
string labeled **"Session pooler"**, not "Direct connection" or
"Transaction pooler."

Not yet verified by a successful deploy — this is the diagnosis from the
real error above; applying it (updating `DATABASE_URL` on the Render
dashboard to the Session pooler string and redeploying) is still an open
step.

Separately — Supabase's (and Neon's, and Railway's) default copy-paste
string is `postgresql://...`, not `postgresql+psycopg://...`. This used
to be a required manual edit (missing it fails with a confusing
`ModuleNotFoundError: No module named 'psycopg2'` deep inside Alembic on
first deploy — hit exactly this in a real deployment). It's no longer
something you need to remember: `app/config.py`'s `Settings` normalizes a
bare `postgresql://`/`postgres://` URL to the `+psycopg` form
automatically. Paste Supabase's direct-connection string as-is.

## Frontend: unaffected, stays on Cloudflare Pages

Cloudflare Pages has no equivalent paid-plan gate — the existing
`deploy-frontend.yml` workflow and `apps/frontend/wrangler.toml` are
unchanged and still the deployment path for the web app. Only
backend/MCP moved off Cloudflare Containers.

## Cloudflare Containers workflows: not deleted, just manual now

`.github/workflows/deploy-backend.yml` and `deploy-mcp.yml` no longer
trigger on push (they were failing every time with "Unauthorized" against
a Free-plan account, which is just noise, not a real signal). They're
still there, still correct, and still runnable via `workflow_dispatch`
whenever the Cloudflare account is on Workers Paid and Containers is the
preferred path again.

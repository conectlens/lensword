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
   - `DATABASE_URL` — **your Supabase project's *direct* connection
     string** (port `5432`), not the pgbouncer pooler (port `6543`). See
     "Supabase-specific: which connection string" below for why.
   - `SECRET_KEY` — generate with `openssl rand -hex 32`, or let Render's
     "Generate" button do it.
   - `CORS_ORIGINS=["https://lensword.conectlens.com","https://lensword-frontend.pages.dev"]`
   - `AI_PROVIDER=none` (or `ollama` if actually configuring that)
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

Supabase gives you two connection strings for the same database:

- **Direct connection** (port `5432`) — a normal Postgres connection, no
  pooler in front of it.
- **Pooler / Transaction mode** (port `6543`, pgbouncer) — built for
  serverless functions that open/close many short-lived connections
  quickly. Transaction-mode pgbouncer does not support some things
  SQLAlchemy and Alembic use (server-side prepared statements, certain
  session-level operations), which can surface as confusing migration or
  query failures that don't look like a connection problem at first.

This app already does its own connection pooling in-process
(`DB_POOL_SIZE`/`DB_MAX_OVERFLOW` in `apps/backend/.env.example`) and runs
as a persistent container (not a serverless function), so it has no need
for Supabase's pooler layer at this scale — **use the direct connection
string** for `DATABASE_URL` and this entire class of problem doesn't come
up. Supabase's dashboard labels both clearly on the project's Database
settings page; copy the one marked "Direct connection," not "Transaction
pooler" or "Session pooler."

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

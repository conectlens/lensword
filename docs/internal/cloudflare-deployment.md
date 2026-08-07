# Cloudflare deployment setup

Maintainer/ops reference, not part of the published docs site (`srcExclude:
['internal/**']` in `config.mts`). Covers the three deploy workflows added
for this repo and exactly what to configure before they can run
successfully.

> **Cloudflare Containers (backend/MCP) requires the Workers Paid plan
> ($5/mo minimum)** — confirmed by an actual "Unauthorized" failure
> deploying against a Free-plan account, not assumed from pricing docs.
> `deploy-backend.yml`/`deploy-mcp.yml` are manual-trigger only
> (`workflow_dispatch`) until that's upgraded. **[render-deployment.md](./render-deployment.md)**
> is the free path in active use today for those two services — Pages
> (frontend) has no such gate and is unaffected.

## What's deployed, and how

| Service | Cloudflare product | Config | Workflow |
|---|---|---|---|
| `apps/frontend` | Pages (static assets) | `apps/frontend/wrangler.toml` | `.github/workflows/deploy-frontend.yml` |
| `apps/backend` | Containers (real Docker image, FastAPI/Alembic/Postgres unchanged) — **requires Workers Paid**, see banner above | `apps/backend/wrangler.toml` + `cf-worker/index.ts` | `.github/workflows/deploy-backend.yml` (manual) |
| `apps/mcp` | Containers (remote Streamable HTTP transport only — the default stdio transport has no server to deploy) — **requires Workers Paid** | `apps/mcp/wrangler.toml` + `cf-worker/index.ts` | `.github/workflows/deploy-mcp.yml` (manual) |

**Why Containers, not classic Workers, for backend/MCP:** both are real
Python processes (FastAPI+uvicorn+Alembic+psycopg for the backend; a
stdlib HTTP server for MCP's remote transport) — the classic Workers
runtime (V8 isolates) can't run a persistent Python server process with a
native Postgres driver. Cloudflare Containers run the existing Docker
images as-is, fronted by a small Worker that forwards requests to the
running container via a Durable Object binding
(`cf-worker/index.ts` in each app). **Cloudflare does not host Postgres**
— `DATABASE_URL` must point at a real external Postgres (Neon, Supabase,
Railway, RDS, etc.), reachable directly from the container over normal
outbound networking.

Every `wrangler.toml`/`cf-worker/index.ts` file has a header comment
flagging it as written from Cloudflare's documented Containers pattern and
verified with `wrangler deploy --dry-run` (which actually builds the
Docker image and resolves bindings, but cannot verify a real deploy
without live credentials) — re-check
[developers.cloudflare.com/containers](https://developers.cloudflare.com/containers/)
if something doesn't match current behavior.

Triggers: each workflow runs on push to `main` when files under its own
app directory change (`paths:` filter), plus `workflow_dispatch` for a
manual run. Nothing deploys on a PR — only after it's merged to `main`.

## One-time Cloudflare-side setup

1. **Enable Containers on the account** (Cloudflare dashboard → Workers &
   Pages → Containers) if not already active — it's a distinct product
   from classic Workers/Pages.
2. **Create the Pages project once**, or let the first `deploy-frontend.yml`
   run create it — the workflow's `--project-name=lensword-frontend` must
   match whichever name the project ends up with.
3. **Provision an external Postgres** for the backend (any managed
   Postgres works) and have its connection string ready in the
   `postgresql+psycopg://...` form `apps/backend/.env.example` documents —
   the `+psycopg` suffix is required.

## Creating the Cloudflare API token

Dashboard → **My Profile → API Tokens → Create Token → Create Custom Token**.
Scope it to exactly what these workflows need — avoid the broad "Edit
Cloudflare Workers" template, which grants more than required:

- **Account** → `Workers Scripts` → **Edit**
- **Account** → `Workers Containers` → **Edit** (or `Cloudflare Containers`,
  depending on how it's labeled when you create the token — Containers is
  newer and the exact permission-group name may have changed since this
  was written)
- **Account** → `Cloudflare Pages` → **Edit**
- **Account** → `Account Settings` → **Read** (lets Wrangler resolve your
  account ID)
- **User** → `User Details` → **Read**

Restrict **Account Resources** to this one account rather than leaving it
at "All accounts."

## Finding the Account ID

Dashboard → any domain/Workers & Pages overview page → **Account ID** is
shown in the right sidebar. Or: `npx wrangler whoami` after running
`npx wrangler login` locally once.

## Adding the GitHub secrets

**Never paste a token value into a chat with an AI assistant, including
this one** — set secrets yourself, either in the GitHub UI
(Settings → Secrets and variables → Actions → New repository secret) or
via the `gh` CLI, which keeps the value local to your own terminal:

```bash
gh secret set CLOUDFLARE_API_TOKEN --repo conectlens/lensword
gh secret set CLOUDFLARE_ACCOUNT_ID --repo conectlens/lensword
gh secret set BACKEND_DATABASE_URL --repo conectlens/lensword
gh secret set BACKEND_SECRET_KEY --repo conectlens/lensword
gh secret set PRODUCTION_API_URL --repo conectlens/lensword
```

Each command prompts for the value interactively (or reads stdin/a file —
see `gh secret set --help`); nothing is echoed back or logged.

| Secret | Used by | Value |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | all three workflows | the token created above |
| `CLOUDFLARE_ACCOUNT_ID` | all three workflows | from `wrangler whoami` or the dashboard sidebar |
| `BACKEND_DATABASE_URL` | deploy-backend.yml | your external Postgres connection string |
| `BACKEND_SECRET_KEY` | deploy-backend.yml | a long random value — **not** the `.env.example` placeholder; generate with e.g. `openssl rand -hex 32` |
| `PRODUCTION_API_URL` | deploy-frontend.yml | the backend Container's public URL once deployed (e.g. `https://lensword-backend.<your-subdomain>.workers.dev`) — not sensitive (a client bundle exposes its own API URL by definition), kept as a secret only for easy editing |

`apps/mcp/wrangler.toml`'s `LENSWORD_API_URL` and `LENSWORD_MCP_WORKSPACE`
are plain `[vars]` in that file (not secrets) — edit them directly once
the backend's real URL is known. If a deployment ever needs
`LENSWORD_TOKEN`, the commented-out block in `deploy-mcp.yml` shows where
it goes.

## First deploy order

1. `deploy-backend.yml` first (or `workflow_dispatch` it manually) — the
   frontend and MCP configs both reference its URL.
2. Update `apps/mcp/wrangler.toml`'s `LENSWORD_API_URL` and
   `PRODUCTION_API_URL`'s secret value with the real backend URL from step 1.
3. `deploy-mcp.yml` and `deploy-frontend.yml` (either order).

## Verifying locally before relying on CI

```bash
cd apps/backend && npm ci && npx wrangler deploy --dry-run   # builds the real Docker image, resolves bindings — no Cloudflare auth needed
cd apps/mcp && npm ci && npx wrangler deploy --dry-run       # same
cd apps/frontend && npm ci && npm run build && npx wrangler pages deploy dist --project-name=lensword-frontend   # fails on auth without a token — confirms syntax, not a real deploy
```

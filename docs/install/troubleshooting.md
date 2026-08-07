---
title: Troubleshooting
description: Common problems and where their fixes are documented.
---

# Troubleshooting

This page aggregates troubleshooting content that already exists elsewhere
in this documentation, rather than restating it — each link below goes
straight to the relevant section.

## Ollama / local AI

- **"AI suggestions unavailable" with no retry option** — `AI_PROVIDER` is
  `none` (the default). See [Local AI / Ollama](/install/local-ai-ollama) for how to turn the provider on.
- **Suggestions fail from inside Docker even though Ollama is running on
  your machine** — `http://localhost:11434` means *inside the container*.
  See [Running the backend in Docker with Ollama on the host](/install/local-ai-ollama#running-the-backend-in-docker-with-ollama-on-the-host).
- **Not sure which of the three failure modes you're hitting** — an admin
  can call `GET /api/v1/ai-settings/probe`; see
  [Checking your setup](/install/local-ai-ollama#checking-your-setup).

## Database / backend

- **`DATABASE_URL` connection errors** — check the `+psycopg` suffix and
  pool-size guidance in [Local development § Database](/reference/local-development#database).
- **Schema errors after pulling new code** — run
  `cd apps/backend && alembic upgrade head`; the Docker backend does this
  automatically on boot. See [Known gaps](/reference/verification#known-gaps).
- **Backend container never becomes healthy / restarts in a loop** — it runs
  `alembic upgrade head` before starting `uvicorn`, and Compose's backend
  service waits for the `db` service's own health check first. If `db`
  never reports healthy, check `POSTGRES_PASSWORD` is actually set in `.env`
  (the placeholder `change-me` works locally but a genuinely empty value
  will not); if `db` is healthy but `backend` still fails, `docker compose
  logs backend` will show the Alembic error directly.

## Frontend can't reach the API

- **Requests fail, or the browser console shows a CORS error** — the
  backend only accepts requests from origins listed in `CORS_ORIGINS`
  (`apps/backend/app/config.py`). The Compose stack sets this correctly for
  its own ports (`docker-compose.yml`); running the frontend on a different
  port (e.g. a custom Vite port, or a reverse-proxied hostname) needs
  `CORS_ORIGINS` updated to match, or the browser will block every request
  with a CORS error rather than a clear "wrong origin" message.
- **Frontend loads but every API call 404s or times out** — check
  `VITE_API_URL` in `apps/frontend/.env` actually points at the backend
  you're running (`http://localhost:8000` for `npm run dev`,
  `http://localhost:18420` if you're pointing a locally-run frontend at the
  Compose backend instead).
- **Works over HTTP locally, fails once deployed behind TLS** — this
  application does not terminate TLS itself; a production deployment needs
  a real reverse proxy in front of it. See
  [Self-Hosting & Deployment § TLS and origins](/install/self-hosting).

## Authentication / first admin account

- **Can't create an admin account** — either set `FIRST_ADMIN_EMAIL` and
  `FIRST_ADMIN_PASSWORD` in `.env` *before* the first boot (the backend only
  creates this account when the users table is empty), or register a normal
  account through the frontend and promote it with a one-off SQL update:
  `UPDATE users SET role='admin' WHERE email='you@example.com'`.
- **Registration rejects a valid-looking email** — the backend validates
  deliverability, not just syntax, and rejects addresses on reserved/
  special-use domains (e.g. `.local`, `.test`). Use a real or
  `example.com`-style domain for local testing.
- **Logged out unexpectedly** — there is no refresh-token rotation yet; a
  single access token is valid for 7 days and then requires logging in
  again. See [Known gaps](/reference/verification#known-gaps).

## Reminders and notifications

- **Reminder settings save, but nothing ever arrives** — push and email
  notifications have no credentialed provider behind them; the only
  adapter writes the message to the application log. This is stated
  directly in the app's own Settings page, not just in these docs. Desktop
  notifications have a real delivery path but have never been observed on
  a real OS build — see
  [Known gaps](/reference/verification#known-gaps) and
  [Desktop § Platform verification matrix](/install/desktop-app#platform-verification-matrix).
- **Reminders fire at the wrong time** — check the time zone set in
  Settings; reminder times and quiet hours are read on that clock, not the
  server's or the browser's.

## Desktop

- **Gatekeeper (macOS) or SmartScreen (Windows) warning on install** —
  expected; no release has ever been signed. See
  [Install](/install/desktop-app#install).
- **No native notification appears** — this has never been observed on any
  real OS; see [Platform verification matrix](/install/desktop-app#platform-verification-matrix).

## Browser extension / MCP

- **Extension icon or popup doesn't do anything** — it requires a
  configured API URL, bearer token, and group ID entered in the popup; see
  [Browser Extension](/install/browser-extension).
- **MCP client can't reach the server over HTTP** — remote transport is off
  by default and double-gated; see [MCP remote transport](/reference/mcp-remote-transport).

Still stuck? Open an issue: <https://github.com/conectlens/lensword/issues>.

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

## Desktop

- **Gatekeeper (macOS) or SmartScreen (Windows) warning on install** —
  expected; no release has ever been signed. See
  [Installing](/install/desktop-app#installing).
- **No native notification appears** — this has never been observed on any
  real OS; see [What works, and what is not yet verified](/install/desktop-app#what-works-and-what-is-not-yet-verified).

## Browser extension / MCP

- **Extension icon or popup doesn't do anything** — it requires a
  configured API URL, bearer token, and group ID entered in the popup; see
  [Browser Extension](/install/browser-extension).
- **MCP client can't reach the server over HTTP** — remote transport is off
  by default and double-gated; see [MCP remote transport](/reference/mcp-remote-transport).

Still stuck? Open an issue: <https://github.com/conectlens/lensword/issues>.

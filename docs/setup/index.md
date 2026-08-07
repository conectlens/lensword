---
title: Getting Started
description: The fastest verified way to run LensWord locally.
---

# Getting Started

The fastest path that's actually been run end to end is Docker Compose,
which bundles its own Postgres and serves both the API and the web app. It's
the same path used to capture every screenshot in this documentation.

**Prerequisites:** Docker and Docker Compose.

```bash
cp .env.example .env
# Edit .env and set SECRET_KEY and POSTGRES_PASSWORD to real values —
# see the comments in .env.example for how to generate a SECRET_KEY.

docker compose up --build
```

- Frontend: `http://localhost:18421`
- Backend API: `http://localhost:18420` (interactive docs at `/docs`)

Register an account from the frontend, or set `FIRST_ADMIN_EMAIL` /
`FIRST_ADMIN_PASSWORD` in `.env` before first boot to create an admin account
automatically.

**Verified:** `docker compose up --build` builds both containers, boots them
healthy, and serves traffic on the ports above — confirmed by registering,
completing onboarding, creating a vocabulary group with real words, running a
forced-recall review session, and placing a word in a Mind Palace room. See
the screenshots on the [repository README](https://github.com/conectlens/lensword#see-it-in-action).

## Next steps

- Not sure which surface fits what you're trying to do? See [Choose your surface](/learn/choose-a-surface).
- Developing on LensWord itself, without Docker? See [Local development](/reference/local-development).
- Running LensWord for other people, not just yourself? See [Self-hosting & deployment](/install/self-hosting).
- Want local, opt-in AI mnemonic suggestions? See [Local AI / Ollama](/install/local-ai-ollama).

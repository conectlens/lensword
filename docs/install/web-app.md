---
title: Web Application
description: LensWord's primary, publicly usable surface — a Vite/React app served alongside its FastAPI backend.
---

# Web Application

The web app (`apps/frontend`) is LensWord's primary, publicly usable surface
— it's the most complete and CI-tested surface, and the one every screenshot
in this documentation was taken from.

## Run it

```bash
cp .env.example .env
# set SECRET_KEY and POSTGRES_PASSWORD — see .env.example's comments
docker compose up --build
```

- Frontend: `http://localhost:18421`
- Backend API: `http://localhost:18420` (`/docs` for interactive API docs)

This is the same command covered in [Getting Started](/setup/),
verified end to end by registering, completing onboarding, creating a group,
adding words, running a review session, and placing a word in a Mind Palace
room.

## Developing on it directly

If you're changing the frontend or backend code rather than just running the
app, see [Local development](/reference/local-development) for running each without
Docker.

## Running it for other people

The Compose stack above is right for one person running it locally. Running
LensWord *for other people* — managed Postgres, secrets in a platform store,
TLS, more than one instance — is covered in
[Self-Hosting & Deployment](/install/self-hosting), including its current
limitations (log-only push/email notifications, no cross-instance rate
limiting).

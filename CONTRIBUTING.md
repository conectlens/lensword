# Contributing to LensWord

Thanks for your interest in contributing. This document covers how to set up
the project, the conventions used, and how to submit changes.

## Project layout

- `backend/` — FastAPI + SQLite API, hexagonal/clean architecture
  (`domain/` → `application/` → `infrastructure/`/`api/`). See the
  "Architecture" section of the [README](README.md) for the dependency rules.
- `frontend/` — Vite + React + TypeScript + Tailwind SPA, feature-sliced under
  `src/features/`.

## Development setup

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload
```

API docs are served at `http://localhost:8000/docs` while running.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm run dev
```

### Docker (both services)

```bash
docker compose up --build
```

## Running checks before submitting a change

These are the same checks CI runs — run whichever apply to your change before
opening a pull request.

```bash
# Backend
cd backend
.venv/bin/pytest -v

# Frontend
cd frontend
npm run lint
npm run build   # tsc -b && vite build
npm test        # vitest run
```

## Branching and commits

- Branch off `development` — the shared integration branch feature work lands
  on. `main` tracks the last released state; `development` is promoted to
  `main` as a separate, explicit release step, not as part of normal feature
  work.
- Use short, descriptive branch names (e.g. `fix/review-session-timer`,
  `feat/mnemolab-voting`).
- Write commit messages that explain *why* a change was made, not just what
  changed — the diff already shows what changed.
- Keep pull requests focused on a single concern where practical; large
  unrelated changes are harder to review and revert.

## Adding tests

- Backend: add or extend a test in `backend/tests/` covering the use case,
  domain service, or API route you touched. Domain logic
  (`app/domain/services/`) should be tested without going through the API
  where possible, since it has no framework dependencies.
- Frontend: co-locate `*.test.tsx`/`*.test.ts` files next to the component or
  module under test (see `src/components/ui/ProgressRing.test.tsx` or
  `src/lib/api.test.ts` for examples), using Vitest and Testing Library.

## Code style

- Backend: keep the dependency direction intact — `domain/` must not import
  from `infrastructure/` or `api/`. Follow existing patterns for use cases
  (one class per operation) and repositories (interface in `domain/`,
  implementation in `infrastructure/`).
- Frontend: TypeScript strict mode is enabled; avoid `any` where a real type
  is available. ESLint (`npm run lint`) enforces React Hooks rules and flags
  unused imports.

## Opening issues

- Use the bug report or feature request template under **New issue**.
- For security vulnerabilities, do **not** open a public issue — see
  [SECURITY.md](SECURITY.md).

## Submitting a pull request

1. Fork the repository and create a branch from `development`.
2. Make your change, adding or updating tests and documentation as needed.
3. Run the checks above.
4. Open a pull request using the provided template, describing what changed
   and how it was tested.
5. Be responsive to review feedback — small follow-up commits are fine, no
   need to force-push/rebase unless requested.

## Code of Conduct

Participation in this project is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

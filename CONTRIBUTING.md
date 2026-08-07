# Contributing to LensWord

Thanks for your interest in contributing. This document covers how to set up
the project, the conventions used, and how to submit changes.

## Project layout

- `apps/backend/` — FastAPI API on Postgres or SQLite, hexagonal/clean architecture
  (`domain/` → `application/` → `infrastructure/`/`api/`). See the
  "Architecture" section of the [README](README.md) for the dependency rules.
- `apps/frontend/` — Vite + React + TypeScript + Tailwind SPA, feature-sliced under
  `src/features/`.

## Development setup

### Backend

```bash
cd apps/backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload
```

The interpreter is pinned to the version CI runs (see the matrix in
`.github/workflows/ci.yml`). A newer `python3` will usually work for day-to-day
development, but tests that pass on it are not evidence that CI will pass.

The default `DATABASE_URL` is SQLite, so this needs no database server.
Postgres is the deployment target, and CI runs the whole suite against both. To
reproduce the Postgres job locally, point `TEST_DATABASE_URL` at a database the
run may **drop and recreate**:

```bash
TEST_DATABASE_URL=postgresql+psycopg://lensword:lensword@localhost:5432/lensword_test \
  .venv/bin/pytest
```

A change touching models, queries or migrations should be run both ways. A
Postgres-only failure is usually a migration that is valid only in SQLite —
the fixtures build the schema from ORM metadata, so the suite alone would not
catch one.

API docs are served at `http://localhost:8000/docs` while running.

### Frontend

```bash
cd apps/frontend
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm run dev
```

### Desktop shell

Only needed if you are working on `apps/desktop/`. Requires a Rust toolchain
([rustup](https://rustup.rs)); the shell itself additionally needs your
platform's webview development packages, listed in the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

```bash
cd apps/desktop
cargo test -p lensword-api-config     # endpoint validation — no webview needed
cargo fmt --check
cargo clippy -p lensword-api-config -- -D warnings
```

`lensword-api-config` deliberately has no Tauri dependency, so the endpoint
rules can be tested on any machine without a GUI toolchain.

To build an installer locally, build the frontend first — `generate_context!`
embeds that output, and if it is missing the build fails inside a macro
expansion rather than saying what is actually wrong:

```bash
(cd apps/frontend && npm ci && npm run build)
(cd apps/desktop && npx @tauri-apps/cli@2 build)
```

The artifact lands under `apps/desktop/target/release/bundle/`. Locally built
installers are unsigned.

On macOS, `.dmg` bundling ends with an AppleScript step that arranges the
disk-image window in the Finder. It fails with `execution error: An error of
type -10810` when there is no GUI session — over SSH, or from a headless
process — after the `.app` has already been built successfully. Setting `CI=1`
skips that cosmetic step and produces the same installer:

```bash
(cd apps/desktop && CI=1 npx @tauri-apps/cli@2 build)
```

CI runners set `CI` themselves, so the release workflow is unaffected. CI produces the same artifacts for all three
platforms on a `v*` tag, also unsigned unless the repository's signing secrets
are configured. See [docs/releasing.md](docs/releasing.md) for the tag process
and the full list of secrets.

The endpoint the shell connects to is read from `LENSWORD_API_URL`, then from
an `api-endpoint` file in the OS application-config directory, then defaults to
`http://127.0.0.1:8000`. It must be a loopback address or an `https://` origin.

### Docker (both services)

```bash
docker compose up --build
```

## Running checks before submitting a change

These are the same checks CI runs — run whichever apply to your change before
opening a pull request.

To run all of them at once:

```bash
scripts/verify.sh
```

Every gate runs even after one fails, so a single run reports everything that
is broken — the same way CI does, since its jobs run in parallel with
`fail-fast: false`. Pass `--fail-fast` to stop at the first failure instead, or
`--docker` to also build both images. The script exits non-zero if any gate
fails, and prints a per-gate summary either way.

To run a single check directly:

```bash
# Backend
cd apps/backend
.venv/bin/pytest -v

# Frontend
cd apps/frontend
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

- Backend: add or extend a test in `apps/backend/tests/` covering the use case,
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
3. If your change is observable by a user of a LensWord product (Web,
   Desktop, Browser Extension, MCP Server, or Local CLI) — a new feature,
   a fix, a behavior change — add a changelog fragment under `.changes/`
   naming the affected product(s) and the verification you actually
   performed, then validate it: `python scripts/changelog/schema.py
   .changes/your-fragment.yml`. See
   [`.changes/README.md`](.changes/README.md) for the schema, and
   [docs/reference/trust/release-process.md](docs/reference/trust/release-process.md)
   for how it's used downstream. Internal-only changes (refactors, CI
   fixes) still get a fragment — use `type: none` with a `reason` (see
   `.changes/README.md`) rather than `documentation_required: false` alone,
   since the changelog CI check below looks for a fragment's presence, not
   its content.

   **This is enforced in CI** (`.github/workflows/changelog.yml`, #282): a
   PR touching a registered product's source (`apps/frontend`,
   `apps/backend`, `apps/desktop`, `apps/browser`, `apps/mcp`) fails if it
   adds no fragment at all. Run the same checks locally before pushing:

   ```bash
   python scripts/changelog/validate_registry.py
   python scripts/changelog/schema.py .changes/*.yml
   python scripts/changelog/check_product_impact.py --base origin/development --head HEAD
   python scripts/changelog/generate.py   # then check `git diff` is empty
   ```
4. Run the checks above.
5. Open a pull request using the provided template, describing what changed
   and how it was tested.
6. Be responsive to review feedback — small follow-up commits are fine, no
   need to force-push/rebase unless requested.

## Code of Conduct

Participation in this project is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

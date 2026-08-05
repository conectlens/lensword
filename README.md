# LensWord

[![CI](https://github.com/conectlens/lensword/actions/workflows/ci.yml/badge.svg)](https://github.com/conectlens/lensword/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A vocabulary-learning app built around **spaced repetition** and the **memory-palace
(method of loci)** mnemonic technique. FastAPI backend on Postgres or SQLite,
Vite + React + Tailwind frontend, email/password auth, Docker deployment.

## What LensWord does

- **Groups** — personal vocabulary decks ("Spanish Verbs", "Business English")
- **Words** — term, translations, example sentence, personal mnemonic, category,
  synonyms/antonyms/topics, and their own spaced-repetition state
- **Rooms** ("Mind Palace") — a 2D canvas per group where words are dragged to a
  spatial position as a memory anchor
- **Review sessions** — one core forced-recall loop, presented five ways
  (standard, focus/Pomodoro, walking, night wind-down, study-break) — see
  *Design decisions* below for why this is one component, not five
- **MnemoLab** — write and vote on mnemonics for your hardest words
- **Mind map** — radial synonym/antonym/topic visualization per word
- **Forced Recall Engine settings** — per-user intensity and trigger configuration
- **Profile** — stats, streak, real badge computation
- **Admin panel** — real user list/search/suspend/delete and aggregate stats

## Architecture

**Backend** — hexagonal/clean architecture:

```
domain/          entities, value objects, SM-2 scheduler, badge service — pure
                 Python, zero framework dependencies, fully unit-testable
application/     use cases — one per operation, depend only on domain interfaces
infrastructure/  SQLAlchemy models + repository implementations, JWT/bcrypt.
                 Dialect-agnostic: the same models and queries run on Postgres
                 and SQLite, and CI runs the whole suite against both
api/             FastAPI routers, Pydantic schemas, dependency wiring
```

Dependency direction points inward: `api` → `application` → `domain` ←
`infrastructure`. The domain layer has no SQLAlchemy or FastAPI imports at all —
you can read `domain/entities.py` and `domain/services/` with zero web-framework
context.

**Frontend** — Vite + React + TypeScript + Tailwind, feature-sliced:

```
lib/           typed API client + shared types mirroring the backend schemas
context/       auth state
components/ui/ design-system primitives extracted from the templates' UI kit
features/      one folder per bounded context (auth, groups, rooms, review, ...)
```

### Design decisions worth flagging

- **No OAuth, despite the templates showing Google/Microsoft/Facebook buttons.**
  Email/password auth is the only supported flow; the OAuth buttons were dropped
  rather than built as non-functional decoration.
- **One `ReviewSessionPage`, not five.** The focus/walking/night/break templates
  are the same recall mechanic with different pacing and input style (typed vs.
  multiple-choice). Building five near-identical pages would have duplicated the
  session/scoring logic five times. Mode is a query param that changes
  presentation only.
- **Color/type tokens normalized.** The 30 templates don't agree with each other
  (surface color drifts between `#1f1f1f`/`#1E1E1E`, the admin panel template
  uses a completely different blue/Inter scheme, text-secondary drifts between
  gray and a yellowish tan). Normalized to one consistent token set built on a
  `#ffde59` primary and Montserrat, with Poppins for body text, since the
  templates themselves only ever use Montserrat.
- **MnemoLab is per-word, not cross-user-global.** The template gallery shows
  mnemonics from multiple different usernames for what looks like a shared
  "Ephemeral" entry. Building a true cross-user shared-by-word-text catalog
  (decoupled from each user's personal `Word` row) is a bigger modeling change
  than time allowed. The schema supports authorship and voting; each user
  currently sees mnemonics attached to their own word entries.
- **AI mnemonic suggestions are real, opt-in, and local.** MnemoLab can ask a
  locally hosted [Ollama](https://ollama.com) model for a mnemonic. It is off
  by default, so an install that configures nothing behaves exactly as before
  and the UI says plainly that suggestions are unavailable rather than
  pretending to call a provider. See
  [Optional: local AI mnemonic suggestions](#optional-local-ai-mnemonic-suggestions-ollama).
  Image generation is still not implemented — no image provider is wired up.
- **Reminders reach the desktop; push and email still only reach the log.**
  Recall settings (channels, quiet hours, triggers) persist for real, a
  background scheduler registers each reminder and fires it at the configured
  time on the account's own clock, and those settings gate delivery before it
  reaches the notification port.

  The **desktop** channel is now backed by a real adapter. Since the desktop
  app is remote-only (ADR 0002), the backend records what the notification tray
  is owed and the shell collects it and raises a native toast. That path is
  unit-tested end to end, but **no toast has actually been observed on macOS,
  Windows or Linux** — that needs a packaged and, on macOS, signed build
  (ROADMAP 3.1). Treat it as implemented and unverified rather than proven.

  Desktop notifications carry actions — start a session, remind me later, skip
  today — and handling them is idempotent, since an operating system may
  deliver the same activation twice. Two settings govern them: *hide
  notification details* keeps specifics off a lock screen, and *pause
  notifications* stops delivery without unsetting the schedule.

  **Push and email** still have no credentialed provider behind the port: the
  only adapter for them writes the message to the application log, so nothing
  arrives. The settings page says so rather than silently no-op'ing.

## Running it

### Docker (recommended)

```bash
docker compose up --build
```
- Frontend: http://localhost:18421
- Backend API: http://localhost:18420 (docs at `/docs`)

Copy `.env.example` to `.env` next to `docker-compose.yml` and set at least
`SECRET_KEY` and `POSTGRES_PASSWORD` before running in anything but a throwaway
local environment. Optionally set
`FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` to auto-create an admin account on
first boot — otherwise, register normally and promote yourself via a one-off SQL
update (`UPDATE users SET role='admin' WHERE email='you@example.com'`).

**Note:** `docker compose up --build` has been verified end-to-end (both
containers build, boot healthy, and serve traffic on the ports above).

#### Database

The Compose stack runs **Postgres**, and the backend waits for it to pass a
health check before starting, because it runs migrations on boot. The database
port is not published to the host — nothing outside the stack needs it, and the
default `lensword`/`lensword` credentials are only safe while it is
unreachable. Override `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`
for anything that is not a throwaway local environment.

To point the backend at a database you already run, set `DATABASE_URL`:

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/lensword
```

The `+psycopg` suffix is required — without it SQLAlchemy looks for `psycopg2`,
which this project does not depend on. `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`
bound the connection pool; against a managed plan's connection cap, the number
that matters is their sum multiplied by how many backend instances you run.

### Hosted deployment

The Compose stack above runs everything on one host, including its database.
That is right for one person and wrong for a service. Running LensWord *for
other people* — managed Postgres, secrets in a platform store, TLS, more than
one instance — is covered in
**[docs/hosted-deployment.md](docs/hosted-deployment.md)**.

Two things to know before you do: **push and email notifications have no
provider and only write to the log**, and no desktop notification has yet been
observed on a real machine (ROADMAP 3.1). Anyone you host this for will set
reminders and, outside the desktop shell, receive nothing — so say so where
they sign up.

### Local development

```bash
# Backend — defaults to SQLite, so no database server is needed
cd apps/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload

# Frontend (separate terminal)
cd apps/frontend
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm run dev
```

## Desktop

LensWord has a desktop shell (Tauri 2) under `apps/desktop/`. It hosts the same
frontend build as the browser version and talks to a LensWord server over the
network — [ADR 0002](docs/adr/0002-desktop-backend-mode.md) decided the first
release is **remote-only**, so the app does not bundle a database or a Python
runtime and needs a server to point at.

### Installing

Tagged releases build installers for all three platforms and attach them to a
GitHub release: `.dmg` for macOS, `.msi`/`.exe` for Windows,
`.deb`/`.AppImage` for Linux.

> **No release has been published yet.** Until one is, build from source with
> the instructions below. When a release does exist, its artifacts are
> **unsigned** unless the repository's signing secrets are configured — macOS
> will show a Gatekeeper warning and Windows a SmartScreen one. See
> [docs/releasing.md](docs/releasing.md).

### Building from source

Requires a Rust toolchain ([rustup](https://rustup.rs)) and your platform's
webview development packages, listed in the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

```bash
(cd apps/frontend && npm ci && npm run build)   # the shell embeds this build
(cd apps/desktop && npx @tauri-apps/cli@2 build)
```

The artifact lands under `apps/desktop/target/release/bundle/`. On macOS, add
`CI=1` if you are building over SSH or from a headless process — the `.dmg`
step ends with an AppleScript that needs a GUI session.

### Pointing it at a server

The endpoint is read from `LENSWORD_API_URL`, then from an `api-endpoint` file
in the OS application-config directory, then defaults to
`http://127.0.0.1:8000`.

It must be a **loopback address or an `https://` origin**. Plain HTTP to a
remote host is refused rather than silently accepted, so a self-hosted server
the shell will talk to has to serve HTTPS.

### What works, and what is not yet verified

The shell stores your authentication token in the operating system's
credential store (Keychain, Credential Manager, Secret Service) rather than in
webview `localStorage`, and it polls for reminder notifications and raises
native toasts with Start / Remind later / Skip today actions.

**No toast has been observed on any operating system.** The path is
unit-tested end to end, but confirming it needs a signed packaged build
(ROADMAP 3.1). Treat native notifications as implemented and unverified.

Startup, memory and installer-size figures have not been measured either, but
the harness that will measure them exists: `scripts/desktop-baseline.py`. Point
it at a packaged build and it reports every ADR 0001 Phase 3.1 gate with a
pass/fail against the documented bar. Run without `--signed` it labels every
figure `NOT-THE-GATE` and exits non-zero, because signing and notarisation
change startup time and an unsigned number flatters the result. It also prints
the packaged-app checks that need a person, so a report cannot look complete
without them.

### Optional: local AI mnemonic suggestions (Ollama)

MnemoLab can ask a locally hosted model for a mnemonic. Everything runs on your
machine — no API key, no account, and nothing leaves the host. The feature is
**off by default**: an install that sets none of these settings builds no
provider at all and behaves exactly as it did before.

**1. Install Ollama** — download it from [ollama.com/download](https://ollama.com/download),
or on macOS with Homebrew:

```bash
brew install ollama
ollama serve            # leave running; listens on http://localhost:11434
```

**2. Pull a model** (a few GB — this is the slow step, and it is a one-off):

```bash
ollama pull llama3.2
```

**3. Turn the provider on** in `apps/backend/.env`:

```bash
AI_PROVIDER=ollama
OLLAMA_MODEL=llama3.2
OLLAMA_BASE_URL=http://localhost:11434
```

| Setting | Default | What it does |
|---|---|---|
| `AI_PROVIDER` | `none` | `none` disables AI entirely; `ollama` enables local suggestions. Any other value is rejected at startup with a message listing the supported values. |
| `OLLAMA_MODEL` | `llama3.2` | The model name passed to Ollama. Must be one you have pulled. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where the Ollama daemon is listening. |
| `AI_MAX_OUTPUT_TOKENS` | `200` | Upper bound on the length of a generated suggestion. Must be greater than zero — Ollama reads a non-positive value as "no limit", so a zero or negative bound is rejected at startup rather than silently disabling itself. |
| `AI_CONTEXT_MAX_CHARS` | `500` | How much of a word's context is sent to the model. Longer context is truncated. Must be greater than zero. |

Restart the backend, open **MnemoLab**, pick a word and use **Suggest with AI**.

The endpoint (`POST /api/v1/words/{word_id}/mnemonics/suggest`) always answers
HTTP 200 and reports what happened in a `status` field, because a provider
being switched off or temporarily down is a normal state of a healthy install
rather than a server error:

| `status` | When | What MnemoLab shows |
|---|---|---|
| `disabled` | `AI_PROVIDER` is `none` | A calm "AI suggestions unavailable" notice, with no retry — retrying cannot change a setting. |
| `unavailable` | Provider configured but unreachable, timed out, or the model isn't pulled | The reason, plus a retry. |
| `ok` | Success | The suggestion, which you can drop straight into your draft. |

Setting names above match the `Settings` fields `ai_provider`, `ollama_model`
and `ollama_base_url` in `apps/backend/app/config.py`.

#### Checking your setup

An administrator can call `GET /api/v1/ai-settings/probe`. It reports the three
failure modes separately, because they need different fixes and a single "AI
unavailable" tells you nothing about which one you have:

| What it says | What it means | What to do |
|---|---|---|
| `reachable: false`, mentions `OLLAMA_BASE_URL` | Nothing is listening there | Start Ollama, or point `OLLAMA_BASE_URL` at the machine running it |
| `reachable: false`, "did not answer like Ollama" | Something is listening, but it is not Ollama | Check the port — you are probably hitting a proxy |
| `reachable: true`, `ready: false` | Ollama is running, the configured model is not installed | `ollama pull <model>`, or pick one of the models the response lists |
| `ready: true` | Configured model is installed and usable | Nothing |

The route is admin-only: it names the deployment's base URL and every model
installed on that host, which is infrastructure detail rather than something a
learner needs.

#### Running the backend in Docker with Ollama on the host

`http://localhost:11434` means *inside the container*, where nothing is
listening — so the default fails in Docker even when Ollama is running fine on
your machine. This is the single most common way the setup appears broken.

**macOS and Windows** (Docker Desktop) — use the host alias:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

**Linux** — `host.docker.internal` is not provided by default. Either map it
explicitly, which the Compose file can do:

```yaml
services:
  backend:
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      OLLAMA_BASE_URL: http://host.docker.internal:11434
```

or point at the Docker bridge address directly (`http://172.17.0.1:11434`),
which is stable for the default bridge network but not for user-defined ones.

Whichever you choose, Ollama must be listening on more than loopback. By
default it binds `127.0.0.1`, which a container cannot reach even with the
right hostname:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

Binding `0.0.0.0` exposes the daemon to your whole network. On a laptop on an
untrusted network, bind it to the Docker bridge interface instead, or leave the
backend outside Docker.

#### Repeated questions are not re-generated

A local model takes seconds per generation, so identical requests within a
short window are answered from an in-process cache rather than asked again.
Entries are keyed by account, provider and model — a response from one model is
never served for another, and one account's response is never served to
another. Failures are not cached, so a model that was starting up a minute ago
is retried rather than remembered as broken. Changing the AI settings clears
the cache.

## Verification actually run

- **Backend: 96/96 tests passing** (`cd apps/backend && .venv/bin/pytest`) — SM-2
  scheduler edge cases, badge thresholds, full auth/group/word/room/review/
  mnemonic/settings/admin flows, cross-user permission checks, cascade deletes.
  Also boot-tested with a real `uvicorn` process and `curl`, not just
  `TestClient`.
- **Frontend: lints clean** (`eslint`), **type-checks and builds clean**
  (`tsc -b && vite build`), **16/16 unit tests passing** (`vitest run`).
- **Ollama suggestions checked live** against a real daemon running
  `llama3.2`, via `uvicorn` + `curl` rather than mocks. All three documented
  states were observed end to end: `ok` with generated text, `disabled` with
  no AI settings present, and `unavailable` with the provider pointed at a
  port nothing is listening on.
- **The Ollama walkthrough above was followed literally from a clean shell**
  — fresh virtualenv, `pip install`, `.env`, boot, first suggestion — and
  took well under a minute, comfortably inside the 10-minute target.
  Installing Ollama and running `ollama pull llama3.2` are excluded from that
  figure: the model download is several GB and dominated entirely by your
  connection. The MnemoLab suggestion UI itself is covered by unit tests; it
  has not been click-tested in a browser.
- Three real bugs were caught and fixed by the test suite along the way: an
  SM-2 interval that could overflow on long correct streaks, a naive/aware
  datetime mismatch against SQLite, and a SQLAlchemy identity-map staleness bug
  where placements/attempts added mid-request didn't show up in the response.

## Known gaps

- Alembic manages schema changes. Run `cd apps/backend && alembic upgrade head`
  before a direct local server start; the Docker backend runs this automatically.
- No refresh-token rotation — a single 7-day access token. Fine for an MVP, not
  for a production launch.
- Blog/About marketing pages from the templates aren't built — the landing page
  is real; a full blog would need a content backend, which felt out of scope for
  the app itself.
- MnemoLab image generation is intentionally not implemented — that needs
  real credentials and an infrastructure decision for you to make, not
  something to fake. AI *mnemonic* suggestions are implemented and opt-in via
  Ollama.
- Scheduled notification delivery **is** implemented: a durable job dispatches
  due reminders, claims each occurrence so two instances cannot deliver it
  twice, and writes a desktop notification the shell polls for. What is still
  missing is *transport* — push and email have no provider and only write to
  the log, and no desktop toast has been observed on a real machine. So a
  reminder fires and is recorded; whether anyone sees it depends on where they
  are running the app.
- Ollama suggestions have been verified with the backend run directly on the
  host. Reaching a host-installed Ollama daemon from inside the Docker
  containers has not been tested, and `http://localhost:11434` will not resolve
  to the host from within a container.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for
development setup, running tests/lint, and the pull request process. This
project follows a [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

To report a security vulnerability, please see [SECURITY.md](SECURITY.md)
rather than opening a public issue.

## License

[MIT](LICENSE)

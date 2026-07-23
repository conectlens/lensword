# LensWord

[![CI](https://github.com/conectlens/lensword/actions/workflows/ci.yml/badge.svg)](https://github.com/conectlens/lensword/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A vocabulary-learning app built around **spaced repetition** and the **memory-palace
(method of loci)** mnemonic technique. FastAPI + SQLite backend, Vite + React +
Tailwind frontend, email/password auth, Docker deployment.

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
infrastructure/  SQLAlchemy models + repository implementations, JWT/bcrypt
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
- **Notification delivery is configured but not dispatched.** Recall settings
  (channels, quiet hours, triggers) persist for real. Actually sending a push,
  email, or desktop notification on a schedule needs a credentialed provider and
  a background scheduler, neither of which exists here — the settings page says
  so rather than silently no-op'ing.

## Running it

### Docker (recommended)

```bash
docker compose up --build
```
- Frontend: http://localhost:18421
- Backend API: http://localhost:18420 (docs at `/docs`)

Set `SECRET_KEY` in your environment (or a `.env` file next to `docker-compose.yml`)
before running in anything but a throwaway local environment. Optionally set
`FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` to auto-create an admin account on
first boot — otherwise, register normally and promote yourself via a one-off SQL
update (`UPDATE users SET role='admin' WHERE email='you@example.com'`).

**Note:** `docker compose up --build` has been verified end-to-end (both
containers build, boot healthy, and serve traffic on the ports above).

### Local development

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm run dev
```

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

**3. Turn the provider on** in `backend/.env`:

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
and `ollama_base_url` in `backend/app/config.py`.

## Verification actually run

- **Backend: 96/96 tests passing** (`cd backend && .venv/bin/pytest`) — SM-2
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

- No Alembic migrations — `Base.metadata.create_all()` on startup. Fine for this
  stage; add Alembic before your schema needs to evolve under real user data.
- No refresh-token rotation — a single 7-day access token. Fine for an MVP, not
  for a production launch.
- Blog/About marketing pages from the templates aren't built — the landing page
  is real; a full blog would need a content backend, which felt out of scope for
  the app itself.
- MnemoLab image generation and scheduled notification delivery are
  intentionally not implemented (see above) — real credentials/infrastructure
  decisions for you to make, not something to fake. AI *mnemonic* suggestions
  are implemented and opt-in via Ollama.
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

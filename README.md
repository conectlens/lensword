# LensWord

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
- **AI/image generation is honestly stubbed, not faked.** The MnemoLab "AI
  Suggestion" tag and image-generation panel in the templates imply an LLM/image
  provider. None is configured in this build, so the UI says so explicitly
  instead of pretending to call one.
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

## Verification actually run

- **Backend: 49/49 tests passing** (`cd backend && .venv/bin/pytest`) — SM-2
  scheduler edge cases, badge thresholds, full auth/group/word/room/review/
  mnemonic/settings/admin flows, cross-user permission checks, cascade deletes.
  Also boot-tested with a real `uvicorn` process and `curl`, not just
  `TestClient`.
- **Frontend: type-checks clean** (`tsc -b`), **builds clean** (`vite build`),
  **8/8 unit tests passing** (`vitest run`).
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
- MnemoLab AI suggestions and image generation, and scheduled notification
  delivery, are intentionally not implemented (see above) — real credentials/
  infrastructure decisions for you to make, not something to fake.

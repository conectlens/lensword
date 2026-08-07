# Architecture

## Backend — hexagonal/clean architecture

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

## Frontend — Vite + React + TypeScript + Tailwind, feature-sliced

```
lib/           typed API client + shared types mirroring the backend schemas
context/       auth state
components/ui/ design-system primitives extracted from the templates' UI kit
features/      one folder per bounded context (auth, groups, rooms, review, ...)
```

## Design decisions worth flagging

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
  pretending to call a provider. See [Local AI: Ollama-powered mnemonic
  suggestions](local-ai-ollama.md). Image generation is still not implemented —
  no image provider is wired up.
- **Reminders reach the desktop; push and email still only reach the log.**
  Recall settings (channels, quiet hours, triggers) persist for real, a
  background scheduler registers each reminder and fires it at the configured
  time on the account's own clock, and those settings gate delivery before it
  reaches the notification port.

  The **desktop** channel is now backed by a real adapter. Since the desktop
  app is remote-only ([ADR 0002](adr/0002-desktop-backend-mode.md)), the
  backend records what the notification tray is owed and the shell collects it
  and raises a native toast. That path is unit-tested end to end, but **no
  toast has actually been observed on macOS, Windows or Linux** — that needs a
  packaged and, on macOS, signed build (ROADMAP 3.1). Treat it as implemented
  and unverified rather than proven.

  Desktop notifications carry actions — start a session, remind me later, skip
  today — and handling them is idempotent, since an operating system may
  deliver the same activation twice. Two settings govern them: *hide
  notification details* keeps specifics off a lock screen, and *pause
  notifications* stops delivery without unsetting the schedule.

  **Push and email** still have no credentialed provider behind the port: the
  only adapter for them writes the message to the application log, so nothing
  arrives. The settings page says so rather than silently no-op'ing.

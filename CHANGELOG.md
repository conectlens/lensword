# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project does not yet follow a formal versioning scheme (no tagged
releases exist yet).

## [Unreleased]

### Security

- Desktop authentication tokens are kept in the operating-system credential
  store (macOS Keychain, Windows Credential Manager, Linux Secret Service)
  rather than webview `localStorage`, as ADR 0001 requires. A typed adapter
  feature-detects the shell: the browser build is unchanged, while the shell
  routes through native `credential_get`/`credential_set`/`credential_clear`
  commands and never writes the token to `localStorage`. Clearing the
  credential on logout surfaces a failure rather than swallowing it, so a
  transiently unreachable store cannot silently leave a token behind for the
  next launch to re-authenticate. Unit tests assert the token never reaches
  `localStorage` in the shell; the packaged-app verification ADR 0001 also
  requires, on each operating system, is still outstanding.
- Mnemonic suggestion prompts now separate instruction from data. The task
  description is sent in the request's system field, and the word and its
  context travel inside a delimited block introduced as data, so a term
  carrying its own directive is described rather than obeyed. Delimiter
  forgery is blocked for dash lookalikes and zero-width padding as well as
  plain hyphens, so a record cannot fake a boundary that merely renders like
  one. Both fields are truncated before sending (`AI_CONTEXT_MAX_CHARS`,
  default 500), and generation is bounded by `AI_MAX_OUTPUT_TOKENS` (default
  200) so a response cannot grow without limit. Both bounds are rejected at
  startup if set to zero or less.

### Added

- Desktop notifications carry **actions**: start a five-minute session, remind
  me later, or skip today. Handling is idempotent, which is the point rather
  than a nicety — an operating system is allowed to deliver the same activation
  more than once, and there is no way to stop it, so the first action recorded
  is the one that stands and every later callback reports it without repeating
  its effect. *Remind later* re-queues the prompt half an hour on, with its own
  expiry so repeated snoozing cannot extend one notification indefinitely.
  *Skip today* retires that reminder's remaining prompts without disabling it,
  so tomorrow fires normally. Actions lapse after twelve hours and an expired
  notification offers none, rather than showing three buttons that all fail.
  The payload is versioned so a shell older than the backend can tell an
  unfamiliar shape from a familiar one with a new field. (ROADMAP Phase 3.2.)

- Two new Forced Recall settings. **Hide notification details** replaces the
  body with a generic line, because a toast is drawn on lock screens, shared
  screens and second monitors that the person who set the reminder did not
  choose; the stored record keeps the real text. **Pause notifications**
  suppresses delivery without unsetting the schedule, and unpausing gets the
  same reminders back rather than needing them rebuilt.

- A per-tenant isolation audit, kept as a test rather than a document. Every
  endpoint that accepts a resource identifier is exercised from a second
  account and must be denied, and the same request is checked to still succeed
  for its owner — so a passing audit cannot be an endpoint that is broken for
  everyone. A companion check fails when a new identifier-taking endpoint is
  added without being audited, which stops the review going stale the way a
  written one would. **Zero findings**: ownership is enforced in the use-case
  layer on every route, and no collection endpoint returns another account's
  rows. (ROADMAP Phase 4.1.)

- Desktop installers are built by CI. Pushing a `v*` tag builds the shell on
  macOS, Windows and Linux and attaches `.dmg`, `.msi`/`.exe` and
  `.deb`/`.AppImage` artifacts to a **draft** GitHub release, so a tag never
  publishes installers without someone looking at them first. The bundle is
  enabled in the Tauri config with a full per-platform icon set. Builds are
  **unsigned** unless the repository's signing secrets are configured; ADR 0001
  requires signed and, on macOS, notarized artifacts before the measured
  startup/memory baseline (#65) can be taken against them, so that gate is
  unchanged by this. (ROADMAP Phase 3.3.)

- Postgres support, and Postgres as the deployment target. `docker compose up`
  now starts a `postgres:17` service and the backend waits for it to pass a
  health check before booting, since it runs migrations on start. The database
  port is not published to the host. Point `DATABASE_URL` at
  `postgresql+psycopg://…` to use a database you already run; `DB_POOL_SIZE`
  and `DB_MAX_OVERFLOW` bound the connection pool, and connections are
  pre-pinged and recycled below the five-minute idle cutoff common to managed
  providers, so a connection dropped underneath the pool is replaced rather
  than handed to a request. SQLite remains the default for local development,
  so a fresh checkout still runs with no database server installed. CI runs the
  full backend suite against both dialects and applies every migration to an
  empty Postgres database. (ROADMAP Phase 4.0.)

- A desktop notification adapter behind the existing `NotificationChannel`
  port. Because ADR 0002 made the desktop app remote-only, the backend and the
  machine that owns the notification tray are different processes — so the
  adapter durably records what the tray is owed rather than trying to raise a
  toast itself, and a shell collects it over
  `GET /api/v1/desktop-notifications` and confirms with
  `POST /api/v1/desktop-notifications/ack`. The adapter wraps the log adapter
  instead of replacing it, so push, email and in-app delivery are unchanged.
  Collection is scoped to the authenticated account, bounded per call, and
  skips anything older than 12 hours, so a machine that has been offline for a
  week does not fire its whole backlog at once. Acknowledgement is idempotent,
  which the repeated OS callbacks in ROADMAP 3.2 will depend on. **No OS toast
  is drawn yet** — that is the shell's half of the handoff (ROADMAP 3.2).

- The desktop backend mode is decided: the first desktop release is
  **remote-only**, talking to a hosted or self-hosted LensWord server, and no
  Python interpreter or database is bundled into the installer. The loopback
  branch of the endpoint contract is retained and kept working, so bundling a
  local backend later is an additive capability rather than a rewrite. The
  trade-off, the options weighed against it, and the conditions for revisiting
  it are recorded in [ADR 0002](docs/adr/0002-desktop-backend-mode.md), now
  Accepted. This closes the question ADR 0001 deliberately left open; it
  changes no code, since nothing in the shell foreclosed either mode.

- Desktop shell scaffold (Tauri 2), under `desktop/`. The shell hosts the
  existing frontend production build and resolves its API endpoint at runtime
  rather than at build time, so one build can address either a local backend or
  a remote server. The endpoint is validated in the host process and must be
  either a loopback address or an explicit `https://` origin; plain HTTP to a
  remote host is refused rather than silently accepted. Configuration is read
  from `LENSWORD_API_URL`, then a plain-text `api-endpoint` file in the
  application-config directory, then a loopback default; a configured endpoint
  that fails validation is an error rather than a fall-through to the default.
  Browser behavior is unchanged — `VITE_API_URL` still applies there. The shell
  is packaged by CI on a tag (see the installer entry above) but the artifacts
  are **unsigned**, and it still has no native notification support.
- Per-user time zones. An account carries an IANA identifier (for example
  `Europe/Istanbul`), set from the settings screen and defaulting to `UTC`, and
  reminder trigger times and Forced Recall quiet hours are both read on that
  clock. A 09:00 reminder for an account at UTC+3 now fires at 06:00 UTC
  instead of 09:00 UTC, and a 22:00-07:00 quiet window covers that account's
  night rather than UTC's. Daylight-saving edges resolve to exactly one
  delivery: a trigger time that a spring-forward transition skips fires at the
  first valid instant after the gap, and one that an autumn fall-back repeats
  fires on the first occurrence only. Changing the zone re-registers that
  account's reminders immediately. Existing accounts default to `UTC` and are
  unaffected.
- Local AI mnemonic suggestions. `AI_PROVIDER`, `OLLAMA_MODEL` and
  `OLLAMA_BASE_URL` select and configure a provider; `OllamaProvider` talks to
  a local Ollama daemon; MnemoLab's AI control calls the new suggestion
  endpoint. The provider defaults to `none`, so an installation that sets none
  of these behaves exactly as before and keeps showing the existing
  "unavailable" notice. See `README.md` for setup. (ROADMAP Phase 1.)
- Reminders now fire. Creating a reminder registers a job with the background
  scheduler, and the job delivers through the notification port. (ROADMAP
  Phase 2.0.)
- The Forced Recall Engine settings, previously stored but unused, now gate
  delivery. Quiet hours suppress push, email and desktop notifications while
  still delivering in-app, so a reminder caught inside a quiet window does not
  interrupt and the review is waiting at next login. Windows that span
  midnight are handled. (ROADMAP Phase 2.1.)
- Background job scheduler wired into the application lifespan, with
  `NotificationChannel` and `AIProvider` domain ports and a `reminders` table.
  (ROADMAP Phase 0.)
- Repository infrastructure for public contribution: CI (backend tests,
  frontend lint/build/tests, Docker build validation), CodeQL analysis,
  dependency review, Dependabot, issue/PR templates, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, and `SECURITY.md`.

### Fixed

- Deleting a word or a group no longer fails when anything references it.
  `DELETE /api/v1/words/{id}` on a word placed in a room raised a foreign-key
  violation — a 500 — against Postgres, and against SQLite silently left the
  placement, mnemonics, practice exercises and review attempts behind as
  orphans. SQLite does not enforce foreign keys unless `PRAGMA foreign_keys`
  is on, which this project never sets, so the bug was invisible for as long
  as SQLite was the only target. Deleting a group now also removes its rooms,
  placements and reminders. Found by running the new tenant-isolation audit
  against Postgres.
- Mnemonic endpoints now verify that the requesting account owns the word.
  Previously any authenticated user could read and vote on mnemonics attached
  to another account's words.
- A reminder row with an unrecognised recurrence value is logged and skipped
  rather than aborting the startup restore, which previously prevented the
  application from starting at all.
- AI suggestion requests no longer hold a database connection while waiting on
  the model, so a slow or unreachable provider cannot make unrelated endpoints
  unresponsive.
- Provider error details returned to the client no longer include the
  configured base URL.

### Known limitations

- The scheduler's job store is in-process, so running more than one backend
  instance delivers each reminder once per instance.
- Desktop notifications have not been seen on a real desktop. The collect,
  show and acknowledge loop is unit-tested, but observing an actual toast on
  macOS, Windows and Linux needs a packaged build and, on macOS, a signed one
  (ROADMAP 3.1, #65).

- Desktop notifications are queued but not yet shown. The backend records them
  and serves them over the API; no OS toast is drawn until the shell collects
  and displays them (ROADMAP 3.2). README's "configured but not dispatched"
  disclaimer therefore still stands.

## [0.1.0] - 2026-07-22

### Added

- Initial version of LensWord: FastAPI + SQLite backend and Vite + React +
  Tailwind frontend, covering groups, words, rooms (mind palace), spaced
  repetition review sessions, MnemoLab, mind map, forced-recall settings,
  profile/badges, and an admin panel. See `README.md` for full details.

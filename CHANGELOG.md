# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project does not yet follow a formal versioning scheme (no tagged
releases exist yet).

## [Unreleased]

### Added

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
- Desktop OS notifications are not yet dispatched; the desktop channel adapter
  depends on the desktop shell (ROADMAP Phase 3).

## [0.1.0] - 2026-07-22

### Added

- Initial version of LensWord: FastAPI + SQLite backend and Vite + React +
  Tailwind frontend, covering groups, words, rooms (mind palace), spaced
  repetition review sessions, MnemoLab, mind map, forced-recall settings,
  profile/badges, and an admin panel. See `README.md` for full details.

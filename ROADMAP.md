# Roadmap

This roadmap tracks planned work beyond the initial release described in
`CHANGELOG.md`. Each item is tagged with its current state:

- `Planned` — scoped, not started
- `In Progress` — actively being worked on
- `Shipped` — merged and reflected in `README.md`

Consistent with this project's existing norm (see README's *Design decisions
worth flagging*), a feature is only described as working once it actually
works — no stubbed capability is documented as shipped.

## Phase 0 — Foundations (scheduler + provider abstractions)

Shared infrastructure. No user-visible behavior change; everything below
depends on this.

- [x] **0.0** Background scheduler in `backend/app/infrastructure/`, wired
      into the FastAPI app lifespan, with a `jobs/` module for registered
      tasks. *(Shipped)*
- [x] **0.1** `NotificationChannel` domain port (`send(user, message,
      channel)`) with one concrete adapter to start. *(Shipped)*
- [x] **0.2** `AIProvider` domain port (`suggest_mnemonic(word, context) ->
      str`), decoupled from any specific backend, preserving the domain
      layer's zero-framework-dependency boundary. *(Shipped)*
- [x] **0.3** `reminders` table (model + migration): trigger time, recurrence,
      target review group. *(Shipped)*

## Phase 1 — Local AI support (Ollama)

- [x] **1.0** `OllamaProvider` implementing the `AIProvider` port (HTTP client
      to a local Ollama instance), with a clear "provider unavailable" error
      instead of a silent failure. *(Shipped)*
- [x] **1.1** `AI_PROVIDER` / `OLLAMA_MODEL` / `OLLAMA_BASE_URL` settings,
      defaulting to disabled — preserving current stubbed behavior when
      unset. *(Shipped)*
- [x] **1.2** Wire MnemoLab's "AI Suggestion" UI to the new endpoint; keep
      the existing honest "no provider configured" message when none is
      set up. *(Shipped)*
- [x] **1.3** README section documenting Ollama install, model pull, and
      configuration. *(Shipped)*

## Phase 2 — Notifications + local cron reminders

- [x] **2.0** Reminder scheduling use case: on creation, register a job with
      the Phase 0 scheduler that fires at the configured time. *(Shipped)*
- [x] **2.1** Wire the existing Forced Recall Engine settings (channels,
      quiet hours, triggers) to actually gate delivery through the
      notification port. *(Shipped)*
- [ ] **2.2** Desktop OS-notification adapter (depends on Phase 3's shell;
      can use a log adapter until then). *(In Progress — the backend adapter
      exists and durably queues desktop notifications for collection over the
      API. No OS toast is drawn yet: ADR 0002 made the shell a remote client,
      so displaying one is the shell's side of the handoff, tracked in 3.2.)*
- [ ] **2.3** Remove README's "notifications configured but not dispatched"
      disclaimer once true. *(Planned)*

## Phase 3 — Desktop app (macOS / Windows / Linux)

- [x] **3.0** Use Tauri 2 to wrap the existing Vite+React frontend. The
      rationale, security requirements, release gates, and revisit triggers are
      recorded in [ADR 0001](docs/adr/0001-use-tauri-for-desktop-shell.md).
      *(Shipped)*
- [ ] **3.1** Scaffold the chosen shell around the existing `frontend/`
      build output; API client points at either a bundled local backend or
      a remote server via config. *(In Progress — the shell project, the
      validated runtime endpoint, and the frontend adapter exist; the measured
      startup/memory baseline on signed builds that ADR 0001 requires of this
      item does not.)*
- [ ] **3.2** Wire OS-native notifications through the shell's per-platform
      API. *(Planned)*
- [ ] **3.3** CI build+package jobs producing installers for all three
      OSes on tagged releases. *(Planned)*
- [x] **3.4** Decide bundled-local-backend vs. remote-only mode for
      desktop. Decided: the first desktop release is remote-only, and the
      architecture is kept sidecar-ready so bundling stays an additive
      capability rather than a rewrite. Recorded in
      [ADR 0002](docs/adr/0002-desktop-backend-mode.md) (Accepted 2026-08-02),
      including the triggers for revisiting it. *(Shipped — product decision)*

## Phase 4 — Cloud support (multi-tenant hosting)

- [x] **4.0** Migrate SQLite → Postgres; audit for SQLite-specific SQL.
      *(Shipped — Postgres is the deployment target and what `docker compose`
      starts. CI runs the whole backend suite against both dialects and applies
      every migration to an empty Postgres database. SQLite is retained as the
      zero-setup local default, not as a second supported deployment.)*
- [ ] **4.1** Per-tenant data isolation audit across all repository
      queries. *(Planned)*
- [ ] **4.2** Move the scheduler to a durable, horizontally-safe job store
      (Postgres-backed locking or a real queue) — required before running
      more than one backend instance. *(Planned)*
- [ ] **4.3** Hosted-deployment guide (managed Postgres, secrets, TLS),
      distinct from the current self-hosted Docker Compose instructions.
      *(Planned)*

## Phase 5 — Documentation

- [x] **5.0** This file. *(Shipped)*
- [x] **5.1** Update README's AI/notification disclaimers once Phases 1–2
      ship. *(Shipped)*
- [ ] **5.2** Add a "Desktop" section to README once Phase 3 ships.
      *(Planned)*
- [ ] **5.3** Add a hosted-deployment section to README once Phase 4 ships.
      *(Planned)*

## Sequencing notes

- Phase 0 blocks Phases 1 and 2; build it first.
- Phases 1 and 2 can proceed in parallel once Phase 0 lands.
- Phase 3 should wait until Phases 1–2 are real, so the desktop build ships
  genuine features rather than stubs.
- Phase 4 is a data-architecture change, not a feature add. It should be
  scoped and started independently of the others, not bundled into the
  same release cycle.

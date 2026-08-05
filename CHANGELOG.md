# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project does not yet follow a formal versioning scheme (no tagged
releases exist yet).

## [Unreleased]

### Security

- Rate limiting on the four endpoint classes that previously had none: auth
  login (per IP, since there is no account yet), AI generation (enrich,
  converse, evaluate-scenario, generate-path — one shared budget, since all
  four occupy the same local model), outbound URL fetch, and document upload
  (each per account). A caller over budget gets `429` with `Retry-After`
  rather than an opaque failure or an unbounded queue. The limiter is
  in-process and per-instance — correct for the single-instance Compose
  deployment, not enforced across more than one instance behind a balancer;
  `docs/hosted-deployment.md` documents the gap (issue #163).

- URL import fetches a page the server chooses on the user's behalf, so it is
  guarded as the server-side request forgery surface it is: only http and https
  on ports 80 and 443, no embedded credentials, and every address a hostname
  resolves to checked against loopback, private, link-local and reserved space
  — all of them, not the first, since returning one public and one private
  address is the standard way past a check that stops early. Redirects are
  followed by hand and every hop is re-validated, because a 302 to
  `169.254.169.254` is the oldest way past a check applied only to the URL that
  was typed. Bodies are bounded while streaming rather than trusted to a
  Content-Length header, and refusals deliberately do not say what was found,
  so the endpoint cannot be used to scan the network the server sits in. The
  residual DNS-rebinding gap cannot be closed in application code without
  breaking TLS hostname validation; `docs/hosted-deployment.md` now documents
  it and recommends egress restrictions.

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

- `scripts/desktop-baseline.py`, a harness for the ADR 0001 Phase 3.1 desktop
  gates. It measures cold and warm startup, idle memory across the whole
  process tree rather than the parent alone, leftover processes after repeated
  launch/quit cycles, and installer sizes per artefact, reporting each against
  the documented bar. It cannot sign a build and refuses to pretend otherwise:
  without `--signed` every figure is labelled `NOT-THE-GATE` and the run exits
  non-zero, because signing and notarisation change startup time and an
  unsigned measurement flatters the result. The checks that need a person —
  nested-route relaunch, keyboard navigation, the review flow, room
  drag-and-drop, the mind map, seeing a real toast — are printed as a checklist
  rather than skipped silently, so a report cannot look complete without them.

### Changed

- The README no longer says scheduled notification delivery is unimplemented.
  It is: a durable job dispatches due reminders, claims each occurrence so two
  instances cannot deliver it twice, and writes a desktop notification the
  shell polls for. What is still missing is transport — push and email have no
  provider and only write to the log, and no desktop toast has been observed on
  a real machine — so the README now says that instead, which is the true
  statement rather than the outdated one.

- A Practice Lab gathering conversation, role-play, writing correction and
  pronunciation feedback behind one page. The four already existed and were
  scattered across separate routes and buried inside a word's practice flow;
  someone who wanted to practise had to know which of four places to go, which
  is a navigation problem masquerading as four features. They are composed
  rather than rewritten — each keeps its own component and endpoints. Only one
  mode is mounted at a time, so a conversation cannot sit behind a tab holding
  state and in-flight requests. Role-play now shows the words the learner
  already holds for the situation, drawn from their topic tags and expanded
  through the knowledge graph so a word filed elsewhere but confused with an
  on-topic one still surfaces; nothing they do not already have is suggested,
  and a deck too thin to list is said in words rather than shown as a two-item
  list. The pronunciation check now states that it reads a transcript rather
  than audio, which a learner told "accepted" after typing the word would
  otherwise reasonably take for a fake.

- Scenario role-play. Seven situations — job interview, airport, restaurant,
  customer support, meeting, presentation, travel emergency — each with tasks
  to accomplish, which is what a free conversation cannot be scored against.
  An attempt wraps a conversation rather than replacing it, so corrections and
  bounded history are reused and turns go through one transport rather than
  two. Finishing scores vocabulary, grammar, fluency and task completion, but
  an attempt too short to judge is told so instead of being given a number: a
  confident score derived from three messages is the kind of figure a learner
  believes because it looks precise. A dimension the model stayed silent about
  is absent rather than zero, since zero would be a claim the learner did badly
  made on the model's silence, and only tasks the scenario actually set are
  reported as met.

- An AI conversation tutor. Sessions and their turns are stored, corrections
  are shown beside what the learner actually wrote rather than replacing it,
  and the tutor is told about the learner's own vocabulary and recent mistakes
  so the conversation stays close to what they are studying. All of that
  material travels inside the delimited data block, never as instructions — a
  word card whose definition reads "ignore your instructions" is something any
  user can create. The learner's turn is stored *before* the model is called,
  so a model being unreachable never costs them what they typed. Corrections
  are capped per turn, because correcting everything turns a conversation into
  a test, and any correction quoting text the learner did not write is dropped
  rather than shown — a highlight pointing at words nobody typed teaches them
  to ignore highlights entirely. History is bounded from the recent end, so a
  long chat cannot push the instruction out of the model's context window.

- Personalized learning paths. A stated goal — "order food confidently in
  Spain" — becomes a short, ordered set of milestones, each naming a vocabulary
  topic and a word target. Progress is counted from the learner's actual deck
  at read time and never stored, so the bar cannot disagree with the word list
  beside it, and deleting words moves it back. A model's plan is bounded and
  cleaned before anything is stored: over-long plans are truncated, steps
  without a title or topic are dropped, absurd word targets are capped, and a
  plan with nothing usable is reported as unavailable rather than saved as an
  empty path — which would leave the learner unable to tell "no steps needed"
  from "this went wrong". Generation answers with a status rather than an
  error, keeping "AI not configured" distinguishable from "temporarily down".

- Local AI through Ollama as a first-class setup. An admin-only check reports
  whether the daemon is reachable and whether the configured model is actually
  installed, keeping the three failure modes distinct — nothing listening,
  something that is not Ollama, and running-but-no-model — because a single "AI
  unavailable" leaves someone with Ollama running and no model pulled with no
  idea what to do next. Identical requests within a short window are answered
  from an in-process cache rather than re-generated, keyed by account, provider
  and model so a response from one model is never served for another and one
  account's response is never served to another; failures are not cached, so a
  model that was starting up is retried rather than remembered as broken. The
  README now documents Docker host networking for Ollama, which is the single
  most common way the setup appears broken.

- Editable AI-generated word cards. Cards written by a model now carry a
  verification state and a field history, and several can be edited at once.
  Verification is a claim about specific text rather than about a word: if a
  model later rewrites a verified field the badge is withdrawn, because
  otherwise it would vouch for words nobody read. A card no model wrote shows
  no badge at all — "unverified" on something a person typed would invite them
  to verify their own writing. The history records what each field said before,
  who changed it, and distinguishes a bulk edit from a single one, since
  setting a level on forty cards is a different degree of attention from
  changing one. Bulk editing deliberately cannot touch terms or translations:
  a control that could overwrite forty terms with one value is a mistake
  waiting to be made irreversibly, and a field left blank means "leave alone"
  rather than "clear".
- File upload and URL import on the Extract page. The parsers landed in an
  earlier change; nothing in the UI reached them. Both paths put the parsed
  text in the textarea for the user to read and edit before extraction runs —
  a parser can misread a PDF's columns or pull a site's navigation menu, and
  feeding that to the model unseen would produce vocabulary from text nobody
  ever saw.

- Knowledge-graph search and CEFR progress. `GET /api/v1/words/{id}/prerequisites`
  answers "what should I learn before this word?" from related words the
  learner already has at a strictly easier level; `GET /api/v1/words/{id}/related`
  returns everything joined to a word, strongest first, each edge carrying the
  evidence that produced it. Confusion pairs recorded by the mistake log feed
  the graph, so the one relation derived from observed behaviour rather than a
  typed label is also the one that outranks the others. A new profile tab shows
  progress across CEFR levels; it deliberately does not name an overall level,
  because a CEFR level describes what a person can do in a language while what
  we hold is which words are in their deck. Words with no level recorded get
  their own row rather than being distributed or hidden, so the parts still add
  up to the learner's word count.
- A "review my mistakes" session that offers words the learner got wrong and
  has not relearned, regardless of whether the scheduler has come round to
  them. Mistakes expire by successful review rather than by elapsed time: three
  correct answers retire one, and successes recorded before the most recent
  mistake do not count. Resolution is derived from the review log rather than
  stored as a flag, so it cannot drift out of agreement with what happened.
- Recorded mistakes, and a weakness profile built from them. Every incorrect or
  skipped review is filed with its category, and a confusion pair is named only
  when the answer given is another word the learner actually studies — a
  misspelling that resembles one is not evidence of confusing the two. The
  profile reports "not enough evidence yet" rather than an empty list, which
  would read as "you have no weaknesses".

- A hosted-deployment guide (`docs/hosted-deployment.md`) and a README section
  pointing at it, for running LensWord as a service rather than for one person:
  managed Postgres with TLS, secrets in a platform store, how the connection
  pool multiplies across instances, what running several instances now costs
  and guarantees, and what the project does *not* do for you. It leads with the
  fact that push and email delivery are unimplemented, because someone hosting
  this for other people needs to know that before their users do.

- Reminder-time recommendations from real engagement. LensWord can now notice
  that you start a review after most reminders at 20:00 and almost none at
  09:00, and offer to move the reminder — but it will not move it. Reading a
  recommendation changes nothing; accepting one is a separate, explicit action,
  and the schedule you set stays the default. Every recommendation carries the
  engagement rate and sample size for both the suggested hour and the current
  one, so the reason can be checked against the data rather than taken on
  trust. Nothing is suggested without enough evidence — a minimum history, a
  minimum per hour, and a minimum improvement over the current time, so a
  near-tie does not generate a prompt every week. An hour inside quiet hours is
  never suggested however good it looks, and accepting re-derives the
  suggestion rather than trusting the hour sent back, so this cannot become a
  way to set a reminder to any time at all. The analysis is deterministic: the
  same history always gives the same answer. (ROADMAP Phase 3.)

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

- Desktop shell scaffold (Tauri 2), under `apps/desktop/`. The shell hosts the
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
  dependency review, issue/PR templates, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, and `SECURITY.md`.

### Fixed

- FSRS review intervals now actually grow. `FSRSScheduler` re-derived
  stability from the previous interval on every review instead of persisting
  it, which mathematically pinned every FSRS word at a 1.00-day interval
  forever regardless of how many times it was answered correctly — no word
  ever left daily review. `retrievability()` had a related bug: it divided
  elapsed time by `interval_days` instead of `stability`, reporting `R ≈
  0.368` at the exact moment the scheduler's own contract said `R = 0.9`.
  Stability is now persisted (`ReviewState.stability`, a new nullable column
  on `words`) and compounds correctly across reviews. See
  [ADR 0004](docs/adr/0004-memory-scheduling-model.md).

  **Existing data:** every FSRS account's affected words are backfilled with
  a stability consistent with what the buggy scheduler already implied
  (`interval_days / -log(0.9)`), not reset to zero and not reverse-engineered
  from repetition count — the bug made every repetition count converge to the
  same interval, so that count carries no usable signal. SM-2 accounts are
  untouched; SM-2 never used this field. Some affected words will re-earn
  longer intervals faster or slower than their real (unrecoverable) review
  history would have produced.

- `PUT /api/v1/recall-settings` no longer silently resets fields it doesn't
  mention. It rebuilt the settings record from the request schema's defaults
  on every save, so any save that didn't explicitly re-send
  `quiet_hours_start`, `quiet_hours_end`, `notifications_paused` or
  `hide_notification_details` reset them to `None`/`false` underneath
  whatever had set them — and the latter two had no API surface to re-send in
  the first place, despite being enforced on notification delivery. The
  endpoint now applies only the fields present in the request onto the
  persisted record, and both fields are now part of the request/response
  schema.
- The scheduler's claims table no longer grows without bound. `#20` added a row
  per job firing to make delivery exclusive, and wrote a prune for them, but
  nothing ever called it — so the table was append-only for the life of a
  deployment. A daily housekeeping job now runs it.
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

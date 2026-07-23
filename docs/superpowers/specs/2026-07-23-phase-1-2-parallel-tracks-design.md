# Phase 1 completion + Phase 2 start — two-track execution design

Covers issues #22, #23, #24 (Phase 1.1–1.3) and #25, #26 (Phase 2.0–2.1).

## 1. Interpreted Idea

Deliver the five next roadmap items as **two independent, concurrently
executed tracks**, each landing on `development` through its own reviewed
pull request.

The five issues are not five parallel units of work. Each issue body ends
with an explicit `Depends on:` line, which yields two strictly sequential
chains that are independent *of each other*:

```
Track A — AI / Ollama            Track B — Reminders / Notifications
  #22 AI provider settings         #25 Reminder scheduling use case
    ↓ (endpoint must exist)          ↓ (a scheduled job must exist to gate)
  #23 MnemoLab UI wiring           #26 Recall-settings delivery gating
    ↓ (must work before documented)
  #24 README Ollama setup
```

Concurrency is therefore applied where it is real — two implementation
tracks, then a fan-out review wave — rather than forced onto a dependency
chain, where it would produce agents building against files that do not yet
exist.

Track A completes Phase 1 and makes local AI genuinely usable. Track B makes
reminders actually fire and respect user settings, which is the substance of
Phase 2.

## 2. Source Principles

These are drawn from the repository's own established norms, not imposed
from outside.

1. **Honesty over capability claims.** `ROADMAP.md` states: *a feature is
   only described as working once it actually works — no stubbed capability
   is documented as shipped.* Documentation changes (#24) land only after
   the behavior they describe is verified. Roadmap checkboxes flip in the
   same PR that makes them true.
2. **Preserve the domain boundary.** `app/domain/` has zero framework
   dependencies. Ports live in `app/domain/services/`, adapters in
   `app/infrastructure/`. New delivery-gating logic is domain logic and
   must not import FastAPI, SQLAlchemy, or APScheduler.
3. **Default to disabled; degrade honestly.** Existing deployments with no
   new configuration must boot and behave exactly as they do today. An
   unconfigured provider yields an honest "not configured" message, never a
   stack trace or a fabricated result.
4. **Build for the injectable seam.** `OllamaProvider` already accepts a
   `transport` argument and deliberately does not read `app.config` — Phase
   1.0 was written to make Phase 1.1 injectable. The design uses that seam
   rather than working around it.
5. **Evidence before assertions.** No phase is reported complete without
   the command output that proves it.

## 3. Top Priorities

| # | Priority | Why it ranks here |
|---|----------|-------------------|
| P0 | No regression for unconfigured deployments | The largest blast radius. Every existing install has no AI config and no reminders; all must be untouched. |
| P1 | Close the endpoint gap in #22 | `mnemonics.py` has no suggestion endpoint. Unowned between #22 and #23; left implicit it becomes a mid-run blocker. |
| P2 | Reminder fires exactly once | #25's stated verification. Duplicate delivery is the failure mode users notice and resent most. |
| P3 | Quiet hours correct across midnight | A 22:00→07:00 window is the common configuration and the classic off-by-one interval bug. |
| P4 | Documentation matches reality | #24's 10-minute success metric is only meaningful if #23 genuinely works first. |

## 3a. Resolved behavioral decisions

Both were left open by the issue bodies and are settled here.

### D1 — Suggestion endpoint returns 200 with a discriminated state

`POST /api/v1/words/{word_id}/mnemonics/suggest` always returns 200 with an
explicit `status` field. "No provider configured" is a settings state, not a
failure, and is not logged or surfaced as a 5xx.

```json
{ "status": "disabled" }
{ "status": "unavailable", "detail": "Ollama is not reachable at ..." }
{ "status": "ok", "text": "..." }
```

This lets the frontend distinguish a configuration state from a transient
outage without string-matching an error message: `disabled` renders the
existing calm badge, `unavailable` offers a retry, `ok` renders the text.

### D2 — Quiet hours suppress intrusive channels, never the review

A reminder falling inside a quiet-hours window does not produce a push,
email, or desktop notification. It is still delivered through the **in-app**
channel, so the review is waiting at next login rather than lost.

In-app delivery is non-intrusive by construction — it cannot wake anyone —
so this satisfies #26's "not delivered" requirement for every channel a user
would experience as an interruption, while preserving the spaced-repetition
promise that a scheduled review is never silently dropped.

This requires no new persistence and no deferral queue. The policy is a pure
function over data that `RecallSettingsModel` already stores:

```
decide(settings, now) -> set[Channel]
  master disabled        -> {}
  outside quiet hours    -> every channel whose *_enabled flag is set
  inside quiet hours     -> {in_app} if in_app_enabled else {}
```

Keeping it a pure function keeps it in the framework-free domain layer and
makes the midnight-spanning window cases table-testable without a clock.

## 4. Phases

### Phase 0 — Preflight and isolation

**Status: complete except TODO 4.**

- **TODO 0.** Fetch all five issue bodies and extract `Depends on:` lines to
  derive the true execution graph. *Verify:* two chains identified.
  **Done** — A: #22→#23→#24, B: #25→#26.
- **TODO 1.** Confirm `origin/development` is the correct base and is not
  behind on feature work. *Verify:* `git rev-list --left-right --count
  origin/main...origin/development` → `2 0` (main ahead only by merge
  commits). **Done.**
- **TODO 2.** Establish the Ollama environment. *Verify:* daemon reachable
  and a model present in `/api/tags`. **Done** — daemon running,
  `llama3.2:latest` pulled.
- **TODO 3.** Record the baseline test result before any change, so new
  failures are attributable. *Verify:* full `pytest` run captured, exit 0.
  **Done** — **74 passed**, 1 warning, 10.43s, via `backend/.venv`
  (Python 3.12.13, matching CI's 3.12 matrix). Note: the system Python 3.14
  has no `pytest`; all runs must use `backend/.venv/bin/python`.
- **TODO 4.** Create two isolated worktrees off `origin/development`:
  `feat/ai-provider-config` and `feat/reminder-scheduling`. *Verify:*
  `git worktree list` shows both at `43d1441`.

> **Housekeeping (blocked, needs the user):** a stale worktree from the
> merged Phase 1.0 PR still holds the `development` branch at
> `.claude/worktrees/feat+ollama-provider`. It is clean and its remote
> branch is deleted. Removal was denied by the permission classifier; it is
> not blocking, since both tracks branch from `origin/development` directly.

### Phase 1 — Track A ▸ Issue #22: AI provider configuration + endpoint

Runs concurrently with Phase 2.

- **TODO 0.** Add `ai_provider` (`"none"` default), `ollama_model`
  (`"llama3.2"`), `ollama_base_url` (`"http://localhost:11434"`) to
  `Settings` in `app/config.py`. *Verify:* a test asserts all three defaults
  with no environment set.
- **TODO 1.** Add `build_ai_provider(settings) -> AIProvider | None` to
  `app/infrastructure/ai.py`, returning `None` when `ai_provider == "none"`.
  *Verify:* unit test covers both branches and an unknown provider value.
- **TODO 2.** Add a `SuggestMnemonicUseCase` to
  `app/application/use_cases/review.py` that raises a domain error when no
  provider is configured. *Verify:* unit test, no HTTP involved.
- **TODO 3.** Add the provider dependency to `app/api/deps.py` and a
  `POST /api/v1/words/{word_id}/mnemonics/suggest` endpoint to
  `app/api/routers/mnemonics.py`, implementing **D1**. *Verify:* 200
  `{"status":"disabled"}` when unset; 200 `{"status":"unavailable"}` when
  the injected transport refuses; 200 `{"status":"ok"}` with non-empty text
  on success.
- **TODO 4.** Confirm the unconfigured app boots identically to today —
  #22's own stated verification. *Verify:* full suite green with no env set;
  no new startup log lines.
- **TODO 5.** Tick `ROADMAP.md` 1.1 to *Shipped*. *Verify:* diff shows only
  the 1.1 checkbox.

### Phase 2 — Track B ▸ Issue #25: Reminder scheduling use case

Runs concurrently with Phase 1.

- **TODO 0.** Add a `Reminder` domain entity to `app/domain/entities.py` —
  it does not exist yet; only the `ReminderModel` persistence shape does.
  *Verify:* entity is importable with no framework imports.
- **TODO 1.** Add a `ReminderRepository` port to
  `app/domain/repositories.py` and its SQLAlchemy implementation in
  `app/infrastructure/repositories.py`. *Verify:* round-trip test against
  the test database.
- **TODO 2.** Implement `ScheduleReminderUseCase`, registering a job with
  the Phase 0.0 scheduler on reminder creation. *Verify:* job appears in the
  scheduler's job store with the expected trigger time.
- **TODO 3.** Implement the job body that loads due reminders and calls the
  `NotificationChannel` port. *Verify:* **#25's stated test** — a reminder
  five seconds out fires and calls the port **exactly once** (assert call
  count, not merely "called").
- **TODO 4.** Register the job in `app/infrastructure/scheduler.py`
  alongside `dev_heartbeat`. *Verify:* suite green; no job registered when
  there are no reminders.
- **TODO 5.** Tick `ROADMAP.md` 2.0. *Verify:* diff shows only 2.0.

### Phase 3 — Track A ▸ Issue #23: MnemoLab UI wiring

Depends on Phase 1.

- **TODO 0.** Add a typed client call to `frontend/src/lib/api.ts` matching
  the Phase 1 contract. *Verify:* `tsc` clean.
- **TODO 1.** Replace the static "AI suggestions unavailable" badge at
  `MnemoLabPage.tsx:155` with a real action that renders the suggestion.
  *Verify:* the honest unavailable message still renders when the provider
  is off.
- **TODO 2.** Handle the three distinct states — not configured, configured
  but unreachable, success — without an error page. *Verify:* #23's stated
  test, both live (Ollama up) and with the daemon stopped.
- **TODO 3.** Frontend build and typecheck. *Verify:* `npm run build` exits 0.
- **TODO 4.** Tick `ROADMAP.md` 1.2.

### Phase 4 — Track B ▸ Issue #26: Recall-settings delivery gating

Depends on Phase 2.

- **TODO 0.** Add a pure-domain delivery policy in
  `app/domain/services/` implementing **D2** as
  `decide(settings, now) -> set[Channel]`. *Verify:* no framework imports;
  returns a channel set, not a boolean.
- **TODO 1.** Implement quiet-hours evaluation including **windows that
  span midnight**. *Verify:* table-driven tests for `22:00→07:00` (spanning),
  `09:00→17:00` (same-day), equal endpoints, and unset (`None`) hours —
  asserting boundary instants at both window edges.
- **TODO 2.** Gate on channel toggles and the master `enabled` flag.
  *Verify:* master off returns the empty set regardless of channel flags;
  all channels off returns the empty set.
- **TODO 3.** Implement D2's core rule: inside a quiet window the intrusive
  channels (push, email, desktop) are stripped and only `in_app` survives.
  *Verify:* **#26's stated test** — a reminder inside a quiet window
  produces no push/email/desktop send; a companion test asserts the in-app
  send *does* occur, so "not delivered" is never satisfied by dropping the
  review entirely.
- **TODO 4.** Apply the policy in the Phase 2 job, sending once per allowed
  channel. *Verify:* the notification port receives exactly the decided
  channel set — no more, no fewer.
- **TODO 5.** Tick `ROADMAP.md` 2.1.

### Phase 5 — Track A ▸ Issue #24: README Ollama documentation

Depends on Phase 3, and only begins once Phase 3 is verified working.

- **TODO 0.** Document install, `ollama pull`, and the three settings.
  *Verify:* every documented setting name matches `config.py` exactly.
- **TODO 1.** Update README's AI disclaimer to reflect real behavior.
  *Verify:* no claim exceeds what Phase 3 demonstrated.
- **TODO 2.** Follow the written steps literally, from a clean shell, and
  time it. *Verify:* #24's metric — a working suggestion in under 10
  minutes, model download excluded and stated as such.
- **TODO 3.** Tick `ROADMAP.md` 1.3.

### Phase 6 — Concurrent review wave

Five agents in parallel — this is where wide fan-out is genuinely correct,
because reviewing is read-only and has no shared state.

- **TODO 0.** Security review: the new endpoint's authentication and
  ownership checks, SSRF surface of a user-influenced `ollama_base_url`,
  and error messages that might leak internal addresses.
- **TODO 1.** Performance review: a 60-second LLM read timeout on a request
  thread, and scheduler behavior as reminder count grows.
- **TODO 2.** Backend test audit: assert the tests fail without the fix, not
  merely that they pass with it.
- **TODO 3.** Frontend review: the three UI states and typecheck integrity.
- **TODO 4.** Consistency review: `ROADMAP.md`, `README.md`, and
  `CHANGELOG.md` agree with the code, and no capability is over-claimed.

### Phase 7 — Verification gate and merge

- **TODO 0.** Full backend suite on each branch. *Verify:* exit 0, output
  captured verbatim.
- **TODO 1.** Frontend build on Track A. *Verify:* exit 0.
- **TODO 2.** Live end-to-end check with Ollama running. *Verify:* a real
  suggestion is returned.
- **TODO 3.** Open PR A (`Closes #22, #23, #24`) into `development`, filling
  in the repository PR template completely.
- **TODO 4.** Open PR B (`Closes #25, #26`) into `development`.
- **TODO 5.** Merge, then rebase the second track and resolve the expected
  `app/main.py` and `ROADMAP.md` conflicts. *Verify:* suite green
  post-merge on `development`.

## 5. Risks / Constraints

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `ROADMAP.md` conflict between tracks | **Certain** | Low | Both tracks touch different checkbox lines; resolve on second merge. Accepted, not avoided. |
| `app/main.py` / `deps.py` conflict | Medium | Medium | Track A adds provider DI, Track B adds job registration. Keep both additive and append-only. |
| Quiet hours across midnight | Medium | **High** | Explicit table-driven tests (Phase 4 TODO 1). Silent wrong-time delivery is user-visible and erodes trust. |
| SSRF via `ollama_base_url` | Low | **High** | Operator-set setting, not user input. Phase 6 TODO 0 confirms it is never request-influenced. |
| 60s LLM read timeout blocks a worker | Medium | Medium | Flagged in Phase 6 TODO 1. Fix may be deferred with an explicit note rather than silently ignored. |
| Reminder fires twice | Medium | **High** | #25's test asserts exact call count. Durable multi-instance safety is explicitly Phase 4.2, out of scope. |
| #24 written against a broken #23 | Low | Medium | Hard ordering: Phase 5 starts only after Phase 3 is verified. |
| Time-based tests are flaky | Medium | Low | Inject a clock; avoid real `sleep` beyond #25's required 5-second case. |

**Constraints**

- SQLite and in-process APScheduler only; Postgres and durable scheduling
  are Phase 4 and explicitly out of scope.
- The domain layer must remain framework-free.
- No behavior change for deployments with no new configuration.
- `llama3.2` output is non-deterministic — assert on *shape* (non-empty
  string), never on exact text.

## 6. Success Metrics

| Metric | Target | How measured |
|--------|--------|--------------|
| Backend suite | 100% pass, no skips | `pytest` exit 0 on both branches |
| New behavior covered by tests that fail without the fix | Every TODO with a `Verify` | Phase 6 TODO 2 audit |
| Unconfigured-boot regression | Zero | Full suite with no env set |
| Reminder delivery count | Exactly 1 | #25's assertion |
| Quiet-hours cases covered | ≥4, incl. midnight-spanning | Phase 4 test table |
| README time-to-suggestion | < 10 min, download excluded | Timed clean-shell walkthrough |
| Frontend build | Exit 0, no new TS errors | `npm run build` |
| Issues closed | 5 of 5 | Both PRs merged |
| Roadmap accuracy | 5 boxes ticked, 0 over-claims | Phase 6 TODO 4 |

## 7. Final Recommendation

Execute as two concurrent tracks with a five-agent review wave, and treat
the dependency chains as hard ordering rather than advisory.

The single highest-leverage decision in this design is **closing the
endpoint gap explicitly in #22**. It is the one piece of work no issue
actually claims, it sits precisely on the seam between the two issues most
likely to be handed to separate agents, and left implicit it is the most
probable cause of a stalled run.

The second is **refusing to parallelize beyond what the dependency graph
supports**. Five concurrent implementation agents on this issue set would
not be five times faster; it would produce agents writing against a
suggestion endpoint and a `Reminder` entity that do not exist yet, and the
resulting conflicts would cost more than the sequencing saves.

Both open behavioral questions are now settled as **D1** and **D2** in
§3a. Together they removed the two ambiguities most likely to cause an
agent to guess: what the endpoint returns when no provider is set, and what
"not delivered" means during quiet hours. Each had two defensible answers,
so neither should have been decided implicitly by whichever agent reached
the code first.

D2 in particular turned out cheaper than it first appeared. Framed as
"suppress or defer", it suggested a deferral queue and new persistence.
Framed as a channel-set decision over the four flags `RecallSettingsModel`
already stores, it collapses into a pure function with no new state — while
still guaranteeing no scheduled review is silently lost.

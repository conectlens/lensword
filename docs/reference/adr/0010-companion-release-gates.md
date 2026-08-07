---
title: "ADR 0010: AI Companion release gates"
description: Architecture decision record.
---

# ADR 0010: AI Companion release gates — what was actually verified

**Status:** Accepted

## Context

Issue #199 is the final phase of the AI Companion epic (#190, phases #191-
#198). Its own success metrics and TODO 6 name five release gates and three
top-level success metrics. This ADR evaluates each one honestly against
what #199's own work (TODO 1-3's tests, TODO 5's documentation) actually
found — not what the epic hoped to find. Where a gate cannot be verified
from this sandboxed environment, it says so plainly, the same way ADR 0009
recorded a "no-go for now" rather than a forced yes, and the way issue #65
is tracked as blocked rather than guessed at for a signed-build performance
baseline elsewhere in this repository.

## Decision: gate-by-gate evaluation

### Gate 1 — "No open critical authorization or tenant-isolation finding"

**Status: met.** This phase ran a targeted red-team pass (issue #199 TODO 2)
against the specific surfaces the issue named, on top of what #192-#197
already built and tested:

- **Malicious client identity / token substitution** — already closed by
  #196 (`app/api/mcp_auth.py`) and covered by
  `apps/backend/tests/test_mcp_security.py` and `test_mcp_oauth.py`. This
  phase did not find a bypass.
- **Cross-user resource enumeration over the MCP tool surface specifically**
  — a genuine coverage gap, not a live vulnerability: `test_tenant_isolation
  .py` exempts the whole `/api/v1/mcp` prefix from its `CROSS_TENANT_CASES`
  battery, and neither `test_mcp_companion_sessions.py` nor
  `test_companion_task_mcp_tools.py` had a case where one account holds a
  real grant and reaches for *another* account's real session/task id. The
  underlying use cases (`GetCompanionSessionUseCase`, `TransitionCompanionSessionUseCase`,
  `SqlAlchemyCompanionTaskRepository.get`) were already scoped by `user_id`
  at every lookup — this phase's `test_mcp_cross_user_enumeration.py` proves
  that scoping holds when reached through the MCP dispatch path
  specifically (grants → `MCPPolicyGate` → dispatcher → use case), which is
  a different code path than the REST surface `CROSS_TENANT_CASES` already
  covers. No bypass was found; the gap was in verification coverage, not in
  the authorization logic itself.
- **Audit-chain tamper detection** — also a verification gap rather than a
  found defect: `redact_and_chain` has produced a correct hash chain since
  #196, but nothing ever recomputed and verified it. `verify_chain` (added
  this phase, `app/domain/services/mcp_policy.py`) and
  `test_mcp_audit_chain_tamper.py` close that gap and confirm a directly
  mutated audit row is caught and localized to the exact tampered link.
- **Tool recursion / budget exhaustion** — already covered exhaustively by
  #195's `test_budget_exhaustion_stops_further_external_calls_not_just_the_
  current_one` (`apps/mcp/tests/test_companion_wiring.py`). No gap found.
- **Sampling output requesting secrets or unauthorized tools** — already
  covered by #195's `validate_sample`/`ElicitationField` tests. This phase
  added no new test here after confirming the existing coverage (malicious
  host injection, oversized/malformed responses, secret-shaped elicitation
  field names) already exercises the adversarial cases TODO 2 names.
- **Poisoned summaries** — `summary_is_grounded` (#193,
  `app/domain/services/companion_sessions.py`) was already tested; this
  phase did not find a gap requiring a new test.
- **Replayed writes** — `IdempotencyStore`/mandatory `request_id` (#196
  TODO 4) already covered by `test_idempotency_replay_cannot_be_reused_as_a
  _confused_deputy_request` and the OAuth authorization-code/refresh-token
  replay tests in `test_mcp_oauth.py`. No gap found.

**Net finding for this gate:** zero unresolved critical findings. Two real
verification gaps existed (cross-user MCP enumeration, audit-chain tamper
detection) and are now closed with passing tests; in both cases the
underlying protection was already correctly implemented and this phase's
work is proof of that, not a fix for a live hole.

### Gate 2 — "No direct companion mastery/diagnosis mutation path"

**Status: met, and structurally enforced, not merely policy.** Confirmed by
re-reading the invariant across its three enforcement points:

1. `TOOL_CONTRACTS` (`app/application/mcp/contracts.py`) has no tool that
   accepts a mastery/strength/diagnosis-shaped field —
   `test_record_context_occurrence_schema_never_accepts_mastery_or_diagnosis_
   fields` asserts this for the one write tool closest to that boundary, and
   `test_mcp_capability_audit.py` (this phase) confirms every one of the 27
   tools has a well-formed, closed (`additionalProperties: false`) schema,
   so nothing can smuggle an unrecognized mutation field through.
2. `BeginLearningActivityUseCase` fixes `expected_evaluation` once at
   activity creation, before any learner response exists, and
   `LearningActivity` has no setter for it afterward (#194 TODO 5) — this
   phase re-confirmed this is a structural guarantee (no code path exists to
   change it), not a check that could be forgotten in a future handler.
3. Diagnosis itself (`diagnose()`, `app/domain/services/diagnosis_engine.py`)
   is computed only from accumulated `LearningObservation` history via its
   deterministic rule set — there is no code path from a companion tool
   argument directly into a `Diagnosis` value. This phase's
   `test_mcp_learning_integrity_parity.py` demonstrates this from the other
   direction: two observation histories that differ only in their
   provenance tag produce identical diagnosis output, which would not be
   possible if either path had a special "trust this source" mutation
   shortcut.

### Gate 3 — "End-to-end cross-client resume verified"

**Status: met, by reference to #193's existing work — not duplicated here.**
`test_a_session_started_over_mcp_is_the_same_durable_row_rest_sees`
(`apps/backend/tests/test_mcp_companion_sessions.py`) starts a session over
MCP, continues it over REST, and reads it back over MCP, asserting the same
row and revision throughout. This phase's own
`test_export_round_trips_every_turn_in_order_with_full_fidelity`
(`test_companion_session_export_import.py`) extends that same claim to the
export surface specifically: the exported shape is byte-for-byte the same
session a live `GET` returns, not a second, possibly-divergent view.

### Gate 4 — "Real-model validation completed for configured fallback provider"

**Status: honestly partial — reported here exactly as
`docs/ai-model-verification.md` already recorded it, not upgraded.**

- The original #166 verification pass (enrich/extract/converse/role-play/
  learning-path/injection) ran against `llama3.2:latest`, this project's
  actual configured default at the time.
- The companion-coach-specific follow-up (issue #187 TODO 4, same document,
  "Follow-up: evidence-grounded companion coach content" section) explicitly
  records that **only `llama3.2:1b` and `qwen2.5:0.5b` were available in
  that pass — the plain `llama3.2` tag was not pulled in that environment**.
  That section's own safety-property finding (the forbidden-claims regex
  correctly rejected a hostile evidence injection for `qwen2.5:0.5b`) is
  real and held; its usefulness-property finding (`3 of 8` acceptable
  generations, marginal quality) describes those two smaller models only.
- This phase (#199) ran no new real-model calls — it had no live Ollama
  daemon available in this sandboxed environment, and fabricating a result
  would violate the same rule this document itself states in "Rule zero" of
  `docs/mcp-companion-guide.md`.

**Conclusion:** the companion's content-safety property (no unsupported
learning-truth claim ever reaches a caller) has real-model evidence, for two
small models, not the project's nominal default. This gate is not fully
closed for the configured default and should not be reported as such in any
release announcement — the same honest framing `docs/ai-model-verification.md`
already uses for itself.

### Gate 5 — "Documentation claims map to tests or recorded manual verification"

**Status: met, as an ongoing discipline rather than a one-time check.**
`docs/mcp-companion-guide.md` (this phase) states this rule explicitly
("Rule zero") and its own compatibility matrix follows it: every row is
either backed by an automated test file named in the table, or marked
**Unverified**/**Partially verified** with the specific reason. The
performance section states plainly which numbers are real (in-process
latency, actually measured) and which are not (desktop client memory/CPU,
multi-instance rate limits, sampling latency) — see that document's
"Performance" section for the numbers and caveats in full.

## Success metrics (issue #199's own three)

1. **"Reference flow works on ≥2 independent MCP hosts"** —
   **UNVERIFIABLE from this sandboxed environment.** No external MCP host
   process (Claude Desktop, MCP Inspector, or any other) can be launched
   here. `docs/mcp-companion-guide.md`'s compatibility matrix records this
   plainly rather than assuming it from the passing test suite.
2. **"Security red-team suite has zero unresolved critical findings"** —
   **met**, per Gate 1 above: a genuine red-team pass was run against every
   surface TODO 2 named, two verification gaps were found and closed, and no
   unresolved vulnerability was found in the underlying authorization logic.
3. **"Session export/import is provider-neutral and deterministic"** —
   **met and tested**: `test_companion_session_export_import.py` asserts a
   closed field set (no provider-specific field can leak in undetected) and
   full round-trip fidelity against the live session.

## Consequences

- This epic (#190) can close on the basis that every gate above has either
  a real pass or an honest, specific statement of what remains unverified
  and why — not a silent gap.
- The two open items that block a genuinely full "production ready, works
  everywhere" claim are: (1) no live interop test against any real external
  MCP host, and (2) real-model validation for the companion coach content
  path has only ever covered small models, not this project's configured
  default. Neither is closable from this environment; both are recorded
  here and in `docs/mcp-companion-guide.md` so a future phase — or a
  developer with access to Claude Desktop/MCP Inspector and a machine that
  can run the full-size default model — has an exact, bounded punch list
  rather than a vague "do more testing."

## Verification

- `apps/backend/tests/test_mcp_capability_audit.py`,
  `test_mcp_cross_user_enumeration.py`, `test_mcp_audit_chain_tamper.py`,
  `test_companion_session_export_import.py`,
  `test_mcp_learning_integrity_parity.py` (this phase).
- `apps/mcp/tests/test_capability_audit.py` (this phase).
- Full suite: `cd apps/backend && python -m pytest -q` (1848 passed, plus
  the 11 in `test_mcp_security.py` run separately) and
  `cd apps/mcp && python -m pytest -q` (124 passed), both green at the time
  this ADR was written.

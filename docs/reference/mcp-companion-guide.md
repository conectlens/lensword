---
title: AI Companion Guide
description: Setup, permissions, privacy, and what is actually verified — plus an honest MCP host compatibility matrix.
---

# AI Companion: setup, permissions, privacy, and what is actually verified

Issue #199 (Phase 8 of the AI Companion epic, #190). This is the A-to-Z
companion doc: local stdio setup, permissions and scopes, example sessions,
privacy/export/deletion/revocation/audit behavior, and — the point of this
particular document existing — a clear line between a **verified learning
fact** and **AI-generated advice**, plus an honest compatibility matrix that
names exactly which hosts this has and has not actually been run against.

This document does not repeat [`docs/mcp-remote-transport.md`](mcp-remote-transport.md)
(#196's OAuth/Streamable HTTP setup, TLS requirements, and that document's
own "what is real and tested vs. not" section) or
[`apps/mcp/README.md`](https://github.com/conectlens/lensword/blob/development/apps/mcp/README.md) (exact CLI commands and
environment variables). Read this one first for the concepts; read those two
for the exact commands.

## Rule zero: do not claim a host or provider works until it is tested and recorded

This is stated once, here, because it constrains everything below it. The
compatibility matrix in this document lists real rows with real columns
(protocol revision, capabilities, transport, auth mode, known limitations)
for the hosts issue #199 named — and marks the ones that have not actually
been run against a live instance of this server as **unverified**, not as a
quiet pass. Nothing in this document, in
[`docs/mcp-remote-transport.md`](mcp-remote-transport.md), or in any release
note should ever say "works with X" for a value of X that is not either an
automated test in this repository or a manually-recorded verification pass
with a method, a date, and a result — the same discipline
[`docs/ai-model-verification.md`](ai-model-verification.md) already applies
to AI model output claims.

## Local stdio setup (the default, and what most installs need)

```bash
export LENSWORD_API_URL=http://localhost:18420
export LENSWORD_TOKEN='your LensWord access token'
export LENSWORD_MCP_WORKSPACE='/approved'
python3 -m lensword_mcp
```

Point your MCP host's stdio server configuration at this command. See
[`apps/mcp/README.md`](https://github.com/conectlens/lensword/blob/development/apps/mcp/README.md) for the exact CLI entry points
this package also exposes (`add`, `explain`, `diagnose`, `review`,
`import-context`).

`LENSWORD_TOKEN` is your normal LensWord login token — the same one the
first-party web/desktop UI uses. The server derives your identity from it
server-side (`app/api/mcp_auth.py`); there is nothing in the protocol or the
environment for a client to claim a different identity with (issue #196
closed that gap — see `apps/backend/tests/test_mcp_security.py`'s
`test_a_caller_supplied_requester_in_the_body_is_ignored_not_trusted` and
`test_two_accounts_cannot_use_each_others_mcp_grants`).

`LENSWORD_MCP_WORKSPACE` is a bounded, POSIX-style path prefix
(`is_valid_workspace` in `app/api/routers/mcp.py`) used as an additional
scoping key on every grant — not a filesystem path this server reads or
writes, just a caller-chosen label your grants are issued against. `..`
segments and relative paths are rejected.

## Permissions: grants, scopes, and what "once" vs. "always" means

Every MCP tool call is deny-by-default (`MCPPolicyGate` in
`app/domain/services/mcp_policy.py`). Nothing runs without an explicit
grant, and a grant is always scoped to exactly one `(requester, tool,
access class, workspace)` tuple — approving one tool never approves
another, and approving a tool in one workspace never approves it in
another.

A grant's `mode` decides how long it lasts:

- **`once`** — consumed on first successful use; the next call for the same
  tool needs a fresh grant.
- **`always`** — stays valid until explicitly revoked or it expires.
- **`deny`** — an explicit refusal, distinct from simply having no grant row
  at all (both fail closed the same way, but `deny` records that a request
  was actively considered and refused, not merely never asked).

Every tool also carries an `AccessClass` — `read`, `write`, `high_impact`,
or `destructive`. The last two always require confirmation
(`MCPPolicyGate.authorize` returns `requires_confirmation=True` and never
auto-approves them) regardless of grant mode; nothing in this codebase can
mark a tool `high_impact`/`destructive` and have it silently execute.

For **remote** MCP connections (OAuth, issue #196), permissions are
requested and approved as named **scopes** rather than individual tools —
`profile-read`, `vocabulary-read`, `session-read`, `progress-read`,
`conversation-write`, `review-write`, `card-write`, `context-import`. Each
scope expands to a fixed, small set of tools (`app/domain/services/
mcp_scopes.py`'s `SCOPE_TOOLS`) and never grants more than that tool's own
contract already allows — scopes are a consent-time convenience over the
same `MCPPolicyGate`, not a separate or looser authorization system. See
`docs/mcp-remote-transport.md` for the full OAuth flow.

Every decision — granted, denied, rate-limited, or requiring confirmation —
is written to a tamper-evident, hash-chained audit log
(`redact_and_chain`/`verify_chain` in `mcp_policy.py`, and see "Audit" below).

## Daily session and measurable-conversation examples

**A read-only daily check-in** (uses the `daily_check_in` prompt, then reads
two resources; no grant beyond `read`-class tools is needed):

1. Host calls `prompts/get` for `daily_check_in`. The returned prompt text
   references `lensword://me/today` and `lensword://me/profile` by URI —
   your stored facts are never copied directly into the instruction text
   the model sees, which is what keeps a hostile word/mnemonic from ever
   being read as an instruction (see "Prompt injection" below).
2. Host reads `lensword://me/today` (today's due facts) and
   `lensword://me/progress` (weekly progress).
3. The model phrases a summary from those facts. Nothing here writes
   anything.

**A measurable structured activity** (a real write, creates evidence):

1. `lensword.begin_learning_activity` — fixes a prompt and its evaluation
   rule (e.g. "translate 'prestar'", `expected_evaluation: {"word_id": 42}`)
   once, before the learner answers. Nothing downstream can change that
   rule after seeing the response (`LearningActivity` has no setter for it
   — issue #194 TODO 5).
2. `lensword.submit_activity_response` — the learner's answer is evaluated
   against the fixed rule. If the activity type is anything other than
   `free_chat` and its rule names a `word_id`, this produces exactly one
   `LearningObservation` — real evidence a diagnosis/scheduling pass can
   later consult.
3. `lensword.get_activity_result` / `lensword.explain_evidence` — read back
   what was recorded, with citations.

**Free conversation** (never evidence): any turn added through
`lensword.companion_reply`/session turns without going through
`begin_learning_activity`/`submit_activity_response` is free chat. It is
never scored, never produces a `LearningObservation`, and never feeds a
diagnosis — confirmed by
`apps/backend/tests/test_companion_activity_observations.py::test_free_chat_turns_produce_zero_review_observations`.
This is ADR 0008's stated boundary, not an incidental property: "Free
conversation is not measurable evidence."

## Privacy: export, deletion, revocation, audit

- **Export** — `GET /api/v1/companion/sessions/{id}/export` returns the full
  session (every turn, in order, plus status/revision/consent) in a single
  closed, versioned shape (`format: "lensword.companion-session.v1"`) with
  no provider-specific field anywhere in it — verified by
  `apps/backend/tests/test_companion_session_export_import.py`, which
  asserts the exact field set and a full round-trip against the live
  session state.
- **Deletion** — `DELETE /api/v1/companion/sessions/{id}/content` removes
  every turn and replaces the summary with `"[content deleted]"`. The
  session row itself (and its audit trail) remains, so revocation/audit
  history stays intact even after a content deletion — this is deliberate,
  not a partial delete: it is what makes "the session is still exportable
  for audit after a deletion request" a meaningful, tested claim.
- **Revocation** — for remote OAuth connections, `POST /api/v1/mcp/oauth/
  connections/{client_id}/revoke` immediately invalidates every access and
  refresh token issued to that connection and revokes its `MCPGrantModel`
  rows. "Immediately" is tested, not asserted: the very next `/invoke` call
  with the just-revoked token gets `401`
  (`test_revocation_blocks_subsequent_calls_immediately`,
  `apps/backend/tests/test_mcp_oauth.py`).
- **Audit** — every policy decision is appended to a hash-chained log
  (`redact_and_chain`). Sensitive keys (`token`, `password`, `secret`,
  `api_key`, `credential`, `clipboard`, `screenshot`, `authorization`) are
  redacted before hashing, recursively, at any nesting depth — a raw
  request payload is never stored at all (only its SHA-256). The chain is
  now also independently **verifiable**: `verify_chain` recomputes every
  link from its stored `(previous_hash, event, event_hash)` triple and
  reports the first one that no longer matches, and
  `apps/backend/tests/test_mcp_audit_chain_tamper.py` proves a directly
  mutated row (bypassing the normal append-only `_audit()` path) is caught
  and localized to the exact tampered link, not merely "the chain looks
  wrong somewhere."

## Verified learning facts vs. AI-generated advice — the boundary this whole feature rests on

ADR 0008 draws this line once, for every companion phase to build against;
this section restates it for someone using the feature rather than building
it:

| | Verified learning fact | AI-generated advice |
|---|---|---|
| **Source** | LensWord's own deterministic domain services (diagnosis engine, spaced-repetition scheduler, observation history) | A model — client-sampled, a configured local provider, or a deterministic template |
| **Examples** | "This word is due for review", "you answered incorrectly 3 of the last 5 times", "this diagnosis fired because of a demonstrated lapse after prior recall" | "Try recalling it in a sentence", a phrased explanation of *why* a diagnosis fired, an example sentence |
| **Where it comes from in this doc's terms** | Resources (`lensword://me/*`), `get_activity_result`, `explain_evidence` | `lensword.companion_reply`'s generated `text` field |
| **Can a companion session invent one?** | No — never. There is no MCP tool or code path that lets a companion write a mastery/diagnosis/retention value directly (see the release-gate ADR below). | Yes, by design — that is what generation is for. It is validated (`validate_sample` rejects any reply containing `mastery:`/`retention:`/`diagnosis:`-shaped claims or `<tool_call>`/`<secret>` control sequences) but never treated as evidence of anything. |

If a companion reply ever reads as a fact about your learning ("you have
90% retention"), that is either a bug (the validator should have rejected
it — file an issue) or the model paraphrasing a real number LensWord
actually computed and handed it as an evidence citation — never the model's
own invention being trusted as ground truth.

### Prompt injection: what actually happens to hostile stored content

A word, mnemonic, or evidence fact containing text shaped like an
instruction (`"Ignore all previous instructions and..."`) stays inert data.
It is placed only inside a `<learner_facts>`/`<evidence>`-delimited block of
the prompt, never the system prompt, and the model is explicitly told to
treat it as data — confirmed against both a mocked transport
(`test_malicious_stored_fact_stays_data_and_never_becomes_an_instruction`,
`apps/mcp/tests/test_companion_wiring.py`) and, for the underlying content
validators specifically, a real local model in
`docs/ai-model-verification.md`'s injection section. Even if a model *did*
comply with an injected instruction, there is no code path from "the
model's text output" to "another tool call actually runs" — sampled/
generated text is only ever displayed or persisted as a chat turn, never
parsed for commands.

## Compatibility matrix

**Read "Rule zero" above before reading this table.** Rows marked
**Unverified** are not silent failures or guesses — this repository's own
conformance/schema/capability-audit test suite (`apps/backend/tests/
test_mcp_capability_audit.py`, `apps/mcp/tests/test_capability_audit.py`)
proves every declared tool/resource/prompt/template has a real, working
handler and that the `initialize` handshake negotiates protocol versions
correctly, in isolation. None of that is the same as a real external MCP
host actually connecting to a live instance of this server, which this
sandboxed environment cannot do (no way to launch Claude Desktop, MCP
Inspector, or any other third-party host process here). Do not read an
Unverified row as "probably fine" — read it as "not yet checked."

| Host | Protocol revision | Capabilities exercised | Transport | Auth mode | Known limitations | Status |
|---|---|---|---|---|---|---|
| This repo's own `MCPServer` test harness (`apps/mcp/tests/`, `apps/backend/tests/`) | `2025-11-25`, `2025-06-18` (both — see version-negotiation tests) | tools, resources, resource templates, prompts, completion, subscriptions, sampling, elicitation, tasks | stdio (in-process fake pipe) and a real duplex-pipe round trip (`test_stdio_transport_performs_a_real_sampling_round_trip`) | local login-JWT-shaped bearer token (faked) | Not a real external process; proves wire-shape and business logic, not interop | **Verified** (automated, this repo's CI) |
| MCP Inspector | Unknown — not run | tool-only baseline expected | stdio | local bearer token | — | **Unverified** — MCP Inspector was not run in this environment (no way to launch an external Node/Electron process here) |
| Claude Desktop | Unknown — not run | tools, resources, prompts, sampling, elicitation (all advertised; whether Claude Desktop specifically exercises each is unconfirmed) | stdio | local bearer token | — | **Unverified** |
| A generic tool-only MCP host (advertises only `tools`, no `resources`/`sampling`/`elicitation`) | Unknown — not run | tools only | stdio | local bearer token | The server's own code correctly falls back to the deterministic/local-provider reply path when sampling/elicitation capabilities are absent (`test_companion_reply_falls_back_to_local_ai_when_sampling_capability_is_absent`) — this is automated-verified in isolation, not confirmed against a real such host | **Partially verified** — fallback logic is tested; no real such host was connected |
| A resources/prompts-capable host (no sampling) | Unknown — not run | tools, resources, prompts | stdio | local bearer token | Same fallback logic as above applies | **Unverified** against a real host |
| A sampling-capable remote host (OAuth) | Unknown — not run | tools (scoped), resources (scoped subset), OAuth authorization-code+PKCE | Streamable HTTP (`apps/mcp/lensword_mcp/http_transport.py`) | Remote OAuth access token | See `docs/mcp-remote-transport.md`'s "explicitly not implemented" list (no SSE streaming, no distributed rate limiting, narrower remote resource set) | **Unverified interop** — OAuth flow and the HTTP transport's request/response mode are automated-tested end to end against this repo's own test client; no external HTTP MCP host has connected to a live instance |
| LensWord Desktop app (`apps/desktop`) | N/A for this row | The desktop app has a generic stdio MCP *client* registry (`apps/desktop/src-tauri/src/mcp.rs`) for connecting to arbitrary local MCP servers (file, browser, calendar, notes) with workspace-root scoping and per-tool allow-listing | stdio | Whatever the configured server needs (its own credential entry in the OS keyring) | This client registry has never specifically been pointed at `lensword-mcp` in this environment; it is a general-purpose feature, not one built or tested for this companion | **Unverified** for this specific pairing |

## Performance: what was actually measured here, and what was not

Issue #199 TODO 4 asks for resource/tool-call latency, sampling/fallback
latency, session storage growth, multi-instance rate limits, and desktop
client memory/CPU. This environment cannot launch a running desktop process
to sample its memory/CPU, and has no multi-instance deployment to measure
real cross-instance rate-limit behavior against (the rate limiter is
explicitly single-process/in-memory — see `docs/mcp-remote-transport.md`'s
"Shared/distributed rate limiting" caveat, which already states the honest
limitation). Those are **unmeasured here**, following the same precedent
issue #65 set for the signed-build startup/memory baseline in this same
repository: recorded as blocked rather than guessed at.

What *is* real and was actually measured: **in-process request latency**,
timed with a small standalone script
(`apps/backend`'s test client, an in-memory SQLite database, no real
network hop) against the live `/api/v1/mcp/invoke`, `/api/v1/mcp/resource`,
and `/api/v1/mcp/capabilities` handlers — the same code path a real request
runs, minus the network and minus a production database:

| Call | n | min | p50 | p95 | max |
|---|---|---|---|---|---|
| `tools/invoke lensword.search_words` (read) | 20 | 5.91ms | 6.31ms | 6.79ms | 6.79ms |
| `tools/invoke lensword.get_learning_progress` (read) | 20 | 5.99ms | 6.48ms | 10.61ms | 10.61ms |
| `resources/resource lensword://me/due` | 20 | 5.50ms | 6.00ms | 7.88ms | 7.88ms |
| `capabilities` (unauthenticated, no DB read) | 20 | 2.03ms | 2.09ms | 2.31ms | 2.31ms |

**Read this table narrowly.** It is a real measurement of this server's own
request-handling overhead (grant lookup, policy evaluation, audit-chain
write, dispatch) — it is **not** a network-deployed latency baseline: no TLS
handshake, no real network round trip, no Postgres (SQLite in-memory is
faster for small tables than a real deployment's Postgres would be under
load), and no concurrent traffic. It says "this server's own logic is fast
relative to itself," not "a real deployment will respond this quickly."
Sampling/fallback latency (the model-call half of `lensword.companion_reply`)
was not measured here at all — it depends entirely on which model a
connected host samples against, which is exactly the kind of claim this
document's "Rule zero" refuses to guess at.

Session storage growth was not separately measured; `MCPAuditEventModel`
and `CompanionTurnModel` are both simple, append-only, unbounded-by-design
tables with no compaction — an operator running this in production should
plan retention/archival policy the same way they would for any other
audit-log table, which this document is not in a position to size without
knowing real usage volume.

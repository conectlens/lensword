---
title: "ADR 0008: AI Companion architecture"
description: Architecture decision record.
---

# ADR 0008: AI Companion — ownership boundaries and fallback order

**Status:** Accepted

## Context

The AI Companion epic (#190) lets a learner talk to LensWord through an
MCP host (Claude Desktop, or any other MCP-compatible client) rather than
only through the first-party UI. Built without a boundary, this becomes
the same failure mode ADR 0007 already named for AI Learning Diagnosis:
router logic duplicated between the REST conversation endpoint and an MCP
tool wrapper, a model asked to decide things only LensWord's own data can
decide, and free-form chat quietly treated as evidence of what a learner
actually knows.

This ADR draws that boundary before Phase 1 onward (#192-#199) write code
against it, the same role ADR 0007 played for the Learning Diagnosis
epic's later phases.

## Decision

### Three owners, none reaching into another's responsibility

1. **LensWord owns learning facts and policy.** What a learner is due for,
   what they've mastered, what they've gotten wrong, which intervention
   applies, whether an activity counts as measurable evidence — all of it
   is computed by LensWord's own deterministic domain services (the same
   ones ADR 0007 already assigns this role to for diagnosis). An MCP host
   or model is never the source of a fact about a learner's own knowledge.
2. **The model owns generated language.** Phrasing a reply, writing an
   example sentence, explaining *why* a diagnosis fired in conversational
   terms — anything that reads as prose rather than a fact. The model may
   be asked to phrase a conclusion LensWord already reached; it is never
   asked to reach that conclusion (the same rule ADR 0007 states for
   diagnosis confidence, extended here to the companion surface).
3. **The MCP host owns user interaction and approval.** Whether a
   sampling request is honored, whether elicited input is collected,
   whether a write-producing tool call actually runs — LensWord requests
   these through the protocol's own consent primitives and never assumes
   they succeeded silently. A companion tool that writes data (a card, an
   observation, a session) requires the host's own approval flow, not an
   internal LensWord confirmation step that bypasses it.

### Free conversation is not measurable evidence

A companion chat turn is either *free conversation* (no expected answer,
no evaluation rule, nothing derived from it feeds mastery) or a
*structured activity* (a known prompt, a known evaluation rule, a
timed response) — never both, and never something in between that reads
as one but is scored as the other. This is the same distinction #194
(Phase 3) is asked to implement at the tool level; this ADR states it as
the boundary that implementation must satisfy, not a new rule invented
there. Free chat and AI praise are never treated as evidence a learner
has retained anything, regardless of how confident the model's tone is.

### No chain-of-thought or unsupported cognitive claims are stored

A companion session persists normalized turns and structured outcomes —
what was asked, what was answered, whether it was evaluated as correct —
never a model's raw reasoning trace, and never a claim about a learner's
cognition (frustration, confusion, engagement) that wasn't derived from an
observable, structured signal. This mirrors ADR 0007's existing rule that
`Diagnosis.confidence` and evidence counts come only from
`LearningObservation` history, not from a model's self-reported
confidence.

### Fallback order: client sampling → configured local provider → deterministic template

When the companion needs generated content (a reply, an example, a
summary), it is requested in this order, falling through only when the
preceding option is unavailable:

1. **MCP client sampling**, when the connected host advertises it —
   generation happens on the model the *user* selected in their MCP host,
   not one LensWord chose for them.
2. **The account's configured local provider** (`AIProvider`, the same
   port `extract`/`enrich`/`converse` already use) — unchanged from every
   non-companion AI surface this codebase has today.
3. **A deterministic template** — no model call at all. A companion
   session must remain usable, just less fluent, with every AI capability
   disabled.

Every sampled or generated result is validated against LensWord's own
facts before persistence or display, the same way #194's TODO 1 states it
for companion tools specifically — this ADR is the boundary that
requirement is drawn from, not a duplicate of it.

## What this ADR does not do

TODO 0 is the only part of #191 (Phase 0) this ADR closes. The rest of
that phase — extracting conversation orchestration out of the REST router
into an application service both REST and MCP can call (TODO 1), the
actual MCP capability-negotiation implementation (TODO 2), the companion
feature flags (TODO 3, addressed in the same PR as this ADR), the
transport-neutral `CompanionIdentity`/`CompanionSession`/`CompanionTurn`
contracts (TODO 4), and the capability-matrix test suite (TODO 5) — are
refactoring and new-subsystem work this ADR deliberately does not attempt
to fold in alongside a boundary decision. Recording the boundary now,
before any of that code exists, is the same sequencing ADR 0007 used for
Learning Diagnosis: the decision is settled first, so later phases build
against a stated contract rather than whatever shape the first phase's
code happened to take.

## Consequences

### Positive

- Every later Companion phase (#192-#199) has a single stated boundary to
  build against instead of five independent interpretations of "how much
  should the model decide."
- The free-conversation/structured-activity distinction is decided once,
  centrally, rather than re-litigated per companion tool as #194 and later
  phases are built.
- The fallback order guarantees the companion degrades gracefully rather
  than becoming unusable the moment client sampling isn't advertised or a
  local provider isn't configured.

### Negative

- A boundary recorded before any of the code it governs exists is a bet
  that the shape of MCP sampling/elicitation as understood today doesn't
  change enough by the time later phases are built to invalidate it — the
  same bet ADR 0007 made and the same risk: a future phase finding this
  boundary doesn't fit reality should amend this ADR rather than route
  around it silently.

## Verification

No new code changes behavior in this PR beyond the feature flags (TODO 3,
all default off — see the settings migration in this same change). There
is nothing yet for a capability-boundary test to check; `tests/test_diagnosis_architecture_boundary.py`'s
static-import-check pattern is the template TODO 1's future application
service should be covered by once it exists.

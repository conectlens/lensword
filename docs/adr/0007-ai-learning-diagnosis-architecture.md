# ADR 0007: AI Learning Diagnosis — five responsibilities, five owners

**Status:** Accepted

## Context

The AI Learning Diagnosis epic (#180) adds five distinct capabilities to
the review loop: figuring out *why* a word keeps failing, deciding *what*
to do about it, *explaining* that to the learner, running a short-term
*acquisition* loop for new/failed words, and continuing to run FSRS for
everything else. Built without a boundary, this becomes exactly the
failure mode #180's own framing warns about: router conditionals that
check "is diagnosis mode on" scattered through request handlers, a second
scheduler competing with FSRS for the same words, and an LLM asked to
report a confidence number it has no way to actually compute.

This ADR draws the boundary before any of the four phases after this one
write code against it.

## Decision

Five responsibilities, five owners, none of which call into another's
internals:

1. **Deterministic diagnosis** — `app/domain/services/` (a new module,
   built in #183). Pure rules over `LearningObservation` history,
   producing a `Diagnosis`. No AI provider dependency. Must be able to run,
   and be unit-tested, with zero network access.
2. **Intervention selection** — `app/domain/services/` (#185's catalog,
   #184's mechanism work). A deterministic policy choosing among a closed
   strategy catalog given a `Diagnosis` and eligibility rules. Also no AI
   dependency for the *selection* itself.
3. **AI explanation and content generation** — behind the existing
   `AIProvider` port (`app/domain/services/ai_provider.py`), the same
   boundary `extract`/`enrich`/`converse` already use. Consumes a
   `Diagnosis` and an `InterventionPlan` that already exist; produces
   prose, example sentences, or a mnemonic. Never produces the diagnosis,
   the confidence, or the evidence count — those are inputs to it, not
   outputs it can generate.
4. **Same-day acquisition scheduling** — a new `AcquisitionScheduler`
   (#184), operating on a seconds-to-hours horizon for initial acquisition
   and post-lapse recovery. A strategy over an ephemeral `AcquisitionState`,
   not over `ReviewState`.
5. **FSRS long-term scheduling** — unchanged. `spaced_repetition.py`
   remains the sole owner of day-scale and long-term intervals for every
   word, diagnosed or not. Acquisition-loop completion hands off to it
   through one bounded transition (#184), not through per-micro-recall
   FSRS updates.

### The LLM cannot determine retention values, evidence counts, or diagnosis confidence

This is the one rule every later phase must not route around. An LLM has
no access to a learner's actual review history beyond what is explicitly
passed to it, no calibrated notion of what "70% confident" means against
this app's real diagnosis error rates, and every incentive (from its
training) to produce a plausible-sounding number rather than decline to
answer. `Diagnosis.confidence`, evidence counts, and retention/stability
values are computed exclusively by responsibility 1 above, from
`LearningObservation` history. Responsibility 3 may be asked to *phrase*
a diagnosis a rule already reached — "you keep confusing X and Y" — but
is never asked whether that diagnosis is correct or how sure to be about
it.

### Standard review is unchanged when diagnosis mode is disabled

Every behavior in this epic sits behind independently controllable opt-in
flags (`learning_diagnosis_enabled`, `acquisition_loop_enabled`,
`ai_coach_enabled` — see the settings migration in this same phase). With
all three off, the request path through review submission, FSRS
scheduling, and reminder delivery is byte-identical to today: no new
table is read, no new branch is taken. This is verified by the existing
review-flow test suite continuing to pass unmodified, not by a new
diagnosis-specific test — the point is that nothing existing changes.

## Consequences

### Positive

- A diagnosis can be unit-tested against the golden fixture (this
  phase's TODO 3) without a model running, and its accuracy measured
  independently of whatever the AI explanation layer produces.
- FSRS keeps a single, uncontested owner of long-term stability (ADR
  0004), the same guarantee ADR 0006 protects for the Semantic
  Relatedness track.
- An account can be rolled back to standard review at any point by
  flipping the settings flags off, with no data loss: the append-only
  observation/diagnosis history stays intact and simply stops being read.

### Negative

- Five owners instead of one AI-does-everything pipeline is more code to
  wire together, and the boundary has to be actively maintained — a
  future contributor reaching for "just ask the model" for a confidence
  number is the failure mode this ADR exists to catch, not one it
  prevents by construction.

## Verification

`tests/test_diagnosis_architecture_boundary.py` (added in this phase)
statically checks that no module under `app/domain/` imports FastAPI,
SQLAlchemy, an HTTP client, or the Ollama client — the same guarantee
`app.domain.repositories`'s docstring already states in prose, now
enforced as a test rather than a convention.

## Observability and data-lifecycle rules (issue #181 TODO 4)

No persistence exists yet for any of this phase's contracts — #182 adds
it. These rules are recorded now so #182 is built against them rather
than retrofitted:

- **Structured events, not raw objects, get logged.** Five event types
  (`app/domain/services/diagnosis_events.py`) — observation recorded,
  diagnosis produced, intervention scheduled, intervention completed,
  diagnosis corrected — each missing every field that could carry a
  learner's answer or the vocabulary context around it, by construction
  rather than by filter. `as_loggable_dict` refuses to serialize a payload
  that contains a forbidden field name, so a future field addition to one
  of these event types fails a test rather than silently starting to log
  raw text.
- **Export and deletion apply to diagnosis data the same way they apply
  to everything else a user owns.** When #182 adds persistence,
  `LearningObservation`, `Diagnosis`, `InterventionPlan`, and
  `InterventionOutcome` rows must be included in this account's existing
  data-export and account-deletion paths, not left as a second, forgotten
  category of personal data. No new export/deletion endpoint is required
  if the existing ones are extended to cover the new tables; a new one is
  required only if diagnosis data cannot be added to them as-is.
- **Tenant isolation is a property of every future endpoint, not
  retrofitted onto the first one that ships.** No new HTTP endpoint
  exists in this phase — this is a constraint on #182 onward: every
  identifier-bearing route (`/diagnosis/{word_id}`, and equivalents) must
  be covered by the same account-scoping test pattern this codebase
  already uses elsewhere, before merge, not added afterward.

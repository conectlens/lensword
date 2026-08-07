---
title: "ADR 0004: Memory scheduling model"
description: Architecture decision record.
---

# ADR 0004: Memory scheduling model — persisted stability, and why Pimsleur's sub-day rungs stay out of it

**Status:** Accepted

## Context

Issue #173 found that `FSRSScheduler`, the default scheduler for every new
account, was mathematically pinned at a 1.00-day interval and could never
expand. `schedule_next` re-derived stability from the *previous interval*
each time it ran:

```python
stability = max(1.0, state.interval_days or 1.0)
stability *= 1.8 + min(state.repetitions, 10) * 0.08
interval_days = stability * -log(target_retrievability)   # ~0.105x at 0.9
interval_days = max(1.0, interval_days)                   # floor on the OUTPUT
```

Because `interval_days` is roughly one-tenth of the `stability` that produced
it, and the next review re-read `interval_days` as if it *were* stability, the
value shrank back toward the floor every cycle. The floor then caught it: the
maximum reachable stability before the floor is `2.6`, giving a maximum raw
interval of `2.6 × 0.10536 ≈ 0.27` days — always less than 1, always clamped
to exactly 1.00. No word ever left daily review, regardless of how many times
it was answered correctly.

A second, related defect: `retrievability()` divided elapsed time by
`interval_days` rather than by `stability`, so it reported `R ≈ 0.368`
(Woźniak's `e^{-1}` point) at the exact moment the scheduler's own contract —
schedule the review for `R = target_retrievability = 0.9` — said it should
report `0.9`. This is the standard conflation of two different definitions of
memory strength: Woźniak's exponential `R = e^{-t/S}` (where `S` is the time
at which `R = 1/e`) versus FSRS's convention that `S` is the interval at which
`R = 0.9`. The two are related by a constant factor, `-\ln(0.9) ≈ 0.105`, and
using one formula's `S` in the other's produces a self-consistent-looking
number that is off by roughly 9.5x.

## Decision

**Stability is now persisted as first-class state** (`ReviewState.stability`,
a nullable column on `words`), not re-derived from `interval_days` on every
review. `schedule_next` reads and writes it directly; `interval_days` is
purely a display/scheduling artifact computed from it
(`interval_days = stability * -log(target_retrievability)`), never fed back in
as if it were stability.

**The two definitions of `S` are not mixed.** Everywhere in this codebase that
computes retrievability from elapsed time divides by `stability`
specifically, matching the same `target_retrievability` convention the
scheduler used to produce that stability. Nothing in this scheduler uses
Woźniak's `S = e^{-1}` convention; if a future feature needs that curve for a
different purpose, it must use its own clearly-named field rather than reuse
`stability`.

**Pimsleur's sub-day graduated-interval rungs are not adopted here.** The
literature that supports very short (seconds-to-minutes) graduated intervals
is short-term, within-session evidence (Karpicke & Roediger, 2007, Experiment
3), not evidence for a long-term, cross-day notification scheduler; Cepeda et
al. (2008)'s spacing-effect synthesis instead supports *increasing* intervals
for long-term retention, which is what stability-driven FSRS scheduling
already does. Sub-day intervals do still occur here as a legitimate
*consequence* of removing the interval floor (see below) — that is a low-
confidence early estimate settling, not an implementation of Pimsleur's rung
sequence, and it is not treated as one.

## Remediation for accounts affected by the bug

Every FSRS account had `interval_days == 1.0` on every word regardless of true
repetition count, because the floor caught every result identically —
`repetitions` carries no signal the bug did not already destroy. Migration
`20260805_20` backfills `stability` for reviewed FSRS words by inverting the
scheduler's own interval formula (`stability = max(1.0, interval_days /
-log(0.9))`), giving every affected word the same starting stability the
scheduler already implied it had, and lets it diverge correctly from there on
the next review. This is a deliberate **"let it converge"** choice over the
two alternatives considered:

- **Recompute stability from `repetitions`.** Rejected: under the bug, 3
  correct reviews and 30 correct reviews produced the identical `interval_days
  == 1.0`, so `repetitions` cannot distinguish a nearly-new word from a
  long-reviewed one that happened to keep failing back to the floor.
- **Reset every affected word to `ReviewState.initial()`.** Rejected: this
  would present as a regression (every word looking newly-added) for accounts
  that had genuinely reviewed some words far more than others, even though the
  scheduler could not tell them apart either.

SM-2 rows are untouched: SM-2 does not use `stability` and was never affected
by this defect.

## Consequences

### Positive

- FSRS intervals now genuinely grow with repeated correct answers instead of
  converging to a fixed point.
- `retrievability()` matches the scheduler's own stated contract.
- Existing FSRS accounts get a stability floor consistent with what the buggy
  scheduler already implied, rather than a jarring reset.

### Negative

- Very early FSRS intervals can now be sub-day (hours rather than a full day),
  which is mathematically correct for a low-confidence first estimate but is
  a visible behavior change from the old scheduler, which always floored to
  at least one day.
- The backfill cannot recover *true* historical mastery for affected
  accounts — only an estimate consistent with the bug's own output. Some
  affected words will re-earn intervals faster or slower than their real
  history would have produced.

## Sources

- Karpicke, J. D., & Roediger, H. L. (2007). Expanding retrieval practice
  promotes short-term retention, but equally spaced retrieval enhances
  long-term retention. *Journal of Experimental Psychology: Learning, Memory,
  and Cognition*, 33(4), 704–719. (Experiment 3: short-term, within-session
  evidence for graduated intervals.)
- Cepeda, N. J., Vul, E., Rohrer, D., Wixted, J. T., & Pashler, H. (2008).
  Spacing effects in learning: A temporal ridgeline of optimal retention.
  *Psychological Science*, 19(11), 1095–1102.

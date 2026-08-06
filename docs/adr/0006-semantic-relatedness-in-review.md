# ADR 0006: Semantic priming is rejected for the review queue

**Status:** Accepted

## Context

The Semantic Relatedness track (#200) will give LensWord a knowledge graph of
synonyms, antonyms, collocations, and topics (#202, #203). It is tempting to
spend that graph on the review queue itself: show a related word shortly
before or after its target, on the theory that activating a related concept
should make the target easier to recall. That is semantic priming, and this
ADR records the decision not to build it, with the evidence for and against.

### The evidence for rejecting it

- **Magnitude is small.** The Semantic Priming Project (1,661 targets, 768
  subjects) measured first-associate priming at 26 ms at a 200 ms
  stimulus-onset asynchrony and 20 ms at 1200 ms in a lexical decision task;
  naming produced only 6 ms.
- **It decays within seconds.** Deacon et al. (1999) found the priming
  ceiling at roughly 2 seconds or one intervening item — an order of
  magnitude shorter than any realistic gap between review-queue cards.
- **It requires an existing lexical representation.** Priming activates a
  connection between two words someone already knows. A word being learned
  has no such representation yet, so the mechanism cannot apply to exactly
  the population a spaced-repetition queue spends most of its time on: new
  and weak items.
- **It produces no retention benefit.** Even twelve primes do not cause
  long-term semantic priming, while repetition priming was obtained in the
  same experimental design — the two effects are not interchangeable, and
  only one of them lasts.
- **The scheduler hazard is the operative reason, not the small effect
  size on its own.** FSRS reads answer accuracy as its difficulty/stability
  signal (ADR 0004). If priming raises in-session accuracy without raising
  retention — which is exactly what "no long-term benefit" means — a primed
  card would report a false difficulty/stability signal, inflating its
  interval as if it had been genuinely strengthened. This is a scheduler
  correctness problem, not merely an inefficient feature: FSRS's persisted
  `stability` (ADR 0004) exists specifically to reflect actual review
  history, and priming would feed it a number that does not correspond to
  demonstrated retention.

This is specifically about **semantic** priming. Two related phenomena are
not covered by this rejection and are not conflated with it:

- **Repetition priming** — literally re-showing the same item — persists
  from hours to roughly a year, and is not the same mechanism at all. It is
  already what a review queue does by design.
- **Social priming** — behavioral effects from incidental cues — is
  unrelated to lexical/semantic priming and separately has a poor
  replication record; it is mentioned here only to avoid conflating the
  two "priming" literatures.

### The evidence against interleaving/clustering, considered honestly

A different, related idea is worth naming so it does not get smuggled in
under "relatedness": clustering similar items together (or deliberately
interleaving them) to aid discrimination. The case for this is weaker than
it is often presented, and this ADR records the counter-evidence rather
than only the evidence that supports the decision already made:

- A meta-analysis found **d = 0.73 [0.41, 1.05]** on trials-to-criterion
  (interleaving helps you get there faster) but **d = −0.24 [−0.71, 0.23]**
  on post-tests (a confidence interval that crosses zero — no reliable
  post-test effect).
- Vote count across the underlying studies: 6 negative, 2 conditionally
  negative, 1 null, and **4 positive** — not a one-sided literature.
- Ishii (2015)'s result is confounded by visual similarity between items,
  not semantic relatedness specifically.
- Sun & Fang (2021) found the opposite temporal profile from the studies
  the trials-to-criterion result is drawn from.

Read together, the trials-to-criterion effect is real but the durable
learning effect is not established, and specific studies have confounds
that limit how far the positive result generalizes. This is not treated as
a case for building clustering/interleaving in the review queue either —
it is recorded so a future proposal has to engage with the actual state of
the evidence rather than a rounded-up summary of it.

## Decision

**LensWord will not implement semantic priming, prime-target pre-exposure,
or any relatedness-based reordering of the review queue.**

The knowledge graph shipping in #202/#203 is for querying relatedness on
demand (a "related words" panel, diagnosis features in #180's track), not
for silently changing what order cards are shown in or which card follows
which.

### Boundary with #180 §3 (contrast and interference)

#180 §3 rules that separating vs. interleaving similar concepts "must [be
chosen] based on observed errors and learning stage rather than one global
rule." A later phase of this track (Phase 3, not implemented by this ADR)
proposes showing a contrasting word only **at first introduction of a new
word, before any observed errors exist** — a learning-stage rule, not a
global one, and therefore of exactly the kind #180 §3 requires rather than
an exception to it. This boundary is recorded here and confirmed on #180
directly; it does not authorize Phase 3's implementation, only clears the
conflict a reader of both issues would otherwise expect.

### Boundary with #185's closed strategy catalog

#185 declares its intervention catalog closed, with `contrast` as one of
its nine members. A later phase of this track (Phase 5, not implemented by
this ADR) supplies the **mechanism** behind `contrast` — an adjacent
contrast card, an ask-to-relate framing, and FSRS grading isolation so a
contrast card's answer never mutates the target word's own review state.
It does not add a new catalog member and does not decide which
intervention to run; #185 keeps sole ownership of the strategy catalog and
of intervention selection.

### Boundary with #176's queue ordering

#176 owns in-session queue order through its self-adjacency rule (a
minimum number of intervening items between repeats of the same word,
enforced by `LearningStepScheduler`). No phase in the Semantic Relatedness
track reorders the review queue. If a future phase in this track ever
needs to influence queue order, it must go through `LearningStepScheduler`
rather than add a second, competing ordering component.

### Phase 5 implementation boundary and pre-registration (#206)

Phase 5's contrast card is a pair presentation, not a queue item: both words
are carried by one `ContrastCard`, the prompt asks the learner to describe the
difference, and the answer path does not invoke FSRS or mutate `due_at`. The
pair is eligible only when both words have persisted FSRS stability at or above
the provisional default of **21 days**. That threshold is configurable because
Nation's evidence does not identify a principled cutoff; it is an experimental
setting, not a claim about the correct value.

The existing semantic-relatedness opt-in and the new contrast-card sub-setting
are both required, and both default off. A diagnosis planner's `isolate`
decision suppresses a graph-derived synonym/antonym pair; a planner-selected
`contrast` decision takes precedence over that fallback. No contrast response
is recorded as a standard review observation until a later measurement phase
defines how to attribute its delayed outcome.

Before measurement begins, the prediction is registered as follows: compared
with matched uncontrasted pairs at one week, contrast cards are expected to
improve discrimination accuracy while reducing in-session accuracy. A null or
negative one-week result is a valid outcome; if the confidence interval does
not support a positive delayed discrimination effect, the feature will be
reported as null/negative and removed rather than retained because the theory
sounds plausible. This prediction does not treat the expected in-session cost
as a regression.

## Consequences

### Positive

- Closes off a class of feature request ("add priming/relatedness to the
  queue") with a citable answer instead of a re-derivation each time it is
  proposed.
- Protects FSRS's stability signal (ADR 0004) from a source of
  accuracy-without-retention noise that would have been difficult to
  detect after the fact, since it would look like the scheduler working
  correctly.
- Keeps queue ordering, intervention selection, and the strategy catalog
  each owned by exactly one component (`LearningStepScheduler`, #180's
  diagnosis/intervention layer, #185's catalog respectively), rather than
  the knowledge graph adding a fourth, overlapping opinion about what to
  show next.

### Negative

- The knowledge graph's most intuitively appealing use — improving recall
  by showing related words near each other — is the one use this ADR
  takes off the table. Relatedness will only ever be queryable on demand,
  not woven into scheduling.
- A genuinely evidence-based case for interleaving (distinct from priming)
  is not precluded by this ADR, but would need its own ADR built on the
  counter-evidence recorded above, not a re-citation of only the
  supportive half of the literature.

## Addendum: the deck-boundary rule (issue #203 TODO 6)

`knowledge_graph.py`'s edge derivation resolves a lexical association
(a synonym string, an antonym string, a topic tag) against words the
*same learner owns*, by exact casefolded term match. A synonym string
that names a word not in the learner's deck produces no edge — it is
vocabulary they do not study, and an edge to it would point at nothing
a query can follow.

**Kept as-is, with the consequence stated explicitly:** this caps the
feature's recall. A learner who tags "generous" with the synonym
"magnanimous" gets no edge unless "magnanimous" is also a card in their
own deck. The alternative — adding unowned lexical nodes as a second node
type, so an edge could point at a word the learner has not added — was
considered and rejected for this phase: it would mean the graph answers
questions about vocabulary nobody is studying, which is a different and
larger feature (effectively a second, unbounded vocabulary source) than
"relate the cards I already have," and it multiplies every downstream
query (`related`, `prerequisites`, distractor selection) with a
node-type check it does not currently need.

If recall becomes a real limitation later, the fix is additive — a new
node type — not a change to how owned-word edges already work, so this
decision does not need to be revisited to make that possible.

## Sources

- Hutchison, K. A., et al. (2013). The Semantic Priming Project.
  *Behavior Research Methods*, 45(4), 1099–1114. (1,661 targets, 768
  subjects; first-associate priming 26 ms at 200 ms SOA, 20 ms at 1200 ms
  in lexical decision; 6 ms in naming.)
- Deacon, D., Hewitt, S., Yang, C.-M., & Nagata, M. (1999). Event-related
  potential indices of semantic priming using masked and unmasked words:
  evidence that the N400 does not reflect a post-lexical process.
  *Cognitive Brain Research*, 8(3), 293–307. (Priming ceiling at ~2
  seconds / one intervening item.)
- The "even twelve primes do not cause long-term semantic priming, while
  repetition priming was obtained in the same design" result distinguishes
  semantic from repetition priming's durability.
- Meta-analysis of interleaving vs. blocking: trials-to-criterion **d =
  0.73 [0.41, 1.05]**; post-test **d = −0.24 [−0.71, 0.23]**; vote count 6
  negative / 2 conditionally negative / 1 null / 4 positive.
- Ishii, T. (2015). Visual-similarity-confounded interleaving study
  (confound noted, not a clean relatedness result).
- Sun, X., & Fang, X. (2021). Interleaving study with a temporal profile
  opposite the trials-to-criterion literature above.
- ADR 0004 (`docs/adr/0004-memory-scheduling-model.md`): persisted FSRS
  stability and why it must reflect genuine review history.

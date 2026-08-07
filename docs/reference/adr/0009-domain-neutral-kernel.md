---
title: "ADR 0009: Domain-neutral diagnosis kernel"
description: Architecture decision record.
---

# ADR 0009: Domain-Neutral Diagnosis Kernel — audit, extension contract, and go/no-go

**Status:** Accepted (kernel + spike); productization: **no-go for now**

## Context

The AI Learning Diagnosis epic (#180) closes with this phase (#189): can
the "proven diagnosis loop" — `diagnosis_engine.py`'s rules,
`intervention_planning.py`'s strategy catalog, `intervention_efficacy.py`'s
delayed-outcome measurement, and the FSRS scheduler — serve a future
non-language domain (medicine, law, biology, software, exams, university
courses) without forking the engine? This ADR is the audit that answers
"which parts are actually generic" (TODO 0), the decision to add an
additive extension layer rather than rewrite anything (TODO 1), and the
honest result of building one real, narrow spike against it (TODO 2, TODO
5) — followed by the explicit choice not to build a real domain-pack
loader yet (TODO 3) and a short safety-boundary note (TODO 4).

The instruction from the issue that shaped every decision below: **do not
rename everything to generic abstractions until at least one non-language
spike proves the boundary**, and **reject speculative abstraction with no
second use case**. Both are visible in what this phase deliberately does
not build.

## TODO 0: the keep/move/adapt audit

| Concept | Verdict | Why |
|---|---|---|
| `DiagnosisCategory` (`FORGETTING`, `WEAK_ACQUISITION`) | **Keep, generic** | Loss-after-recall vs. never-demonstrated-recall is a pattern over any repeated recall attempt, not a fact about words. |
| `DiagnosisCategory.EXACT_CONFUSION` | **Keep, generic** | "Answered B when asked about A, repeatedly" needs nothing about language — the spike's process/thread pair diagnoses through the unmodified rule. |
| `DiagnosisCategory.MISSING_PREREQUISITE` | **Keep the category; adapt its evidence source** | The *concept* (failing at something before an easier prerequisite is solid) is domain-neutral. Its only real evidence source, `KnowledgeGraph.prerequisites()`, is not — see the CEFR row below. |
| `DiagnosisCategory.RECOGNITION_PRODUCTION_GAP` | **Keep, generic** | Multiple-choice vs. typed/spoken production is a modality distinction any skill domain can have (recognizing vs. producing a diagnosis, a proof step, a syntax construct). |
| `DiagnosisCategory.CONTEXT_LOCK` | **Keep, generic** | Correct in one context, wrong in another, is domain-neutral; it is also structurally unfired today regardless of domain (`context_source` has no write path — #229), so this is a paper finding, not a tested one. |
| `DiagnosisCategory.ORTHOGRAPHIC_INTERFERENCE` | **Adapt: language-specific by name, generic by mechanism** | "Orthographic" literally means spelling. The *mechanism* (near-miss string edit-distance on a typed answer) is reusable for any domain with typed free-text answers; a non-text domain (multiple choice only, diagram labeling) would not produce this evidence at all. Not renamed — no second domain in this phase types free-text answers close enough to a label to need it. |
| `DiagnosisCategory.PHONETIC_INTERFERENCE` | **Language-specific, not moved** | The consonant-skeleton heuristic is explicitly a spoken-language approximation (see its own docstring). No adapter is offered for it in this phase; a spoken-answer domain would need its own evidence source, out of scope here. |
| `DiagnosisCategory.SEMANTIC_DIRECTION_REVERSAL` | **Keep, generic in shape; "semantic" is the misleading part of the name** | Direction asymmetry (right one way, wrong the other) applies to any bidirectional prompt pair — "process depends on threads" vs. "threads belong to a process" is the same shape as term-to-translation vs. translation-to-term. Not renamed for the same anti-speculative-abstraction reason as the row above. |
| `DiagnosisContext.word_id` / `.term` | **Adapt: kept as-is, not renamed** | Structurally generic (an id and a label), but `word_id` is typed `int` — a real coupling to the vocabulary product's own database primary key, not an opaque id. The kernel does not widen this type; instead every `KernelItem` (the kernel's own generic item type) carries a `numeric_id: int` a domain pack supplies. `term`/`word_id` are not renamed to `item_id`/`label` in `diagnosis_engine.py` itself — TODO 0 forbids that without a second real domain, and this phase's spike is not that. |
| `KnowledgeGraph.Relation.SYNONYM` / `.ANTONYM` | **Vocabulary-specific, not moved** | A lexical fact about words. No equivalent is offered in the kernel's `KernelRelation`. |
| `KnowledgeGraph.Relation.CONFUSED_WITH` | **Keep, generic** | "These two are mixed up" needs nothing lexical. The kernel's `KernelRelation.CONFUSABLE` maps directly onto it — the cleanest adaptation in this whole audit, and the one the spike leans on hardest. |
| `KnowledgeGraph.Relation.TOPIC` / `.COLLOCATION` | **Keep, generic (mostly)** | "Share a grouping" (`TOPIC`) and "co-occur" (`COLLOCATION`) are reusable. The kernel exposes `KernelRelation.RELATED` for the `TOPIC` case; `COLLOCATION` has no kernel equivalent since nothing in the spike needed co-occurrence evidence. |
| `KnowledgeGraph.prerequisites()` | **Adapt, with real friction — see the go/no-go section** | Derives "easier related item" from two mechanisms built for vocabulary: any edge connecting two nodes, plus a `cefr_level` string ordinal comparison. Neither is a dedicated "is a prerequisite of" relation. The kernel adapts both rather than fixing either (below). |
| CEFR level handling (`WordNode.cefr_level`, `_CEFR_ORDER`) | **Language-specific — needs a real adapter concept, not built here** | Exactly the issue's own prediction. `KernelItem.difficulty_tier` currently *borrows* the literal `"A1"`–`"C2"` strings as an ordinal encoding so `KnowledgeGraph.prerequisites()` has something to compare — this is a stand-in, not a difficulty-tier concept, and is called out as such in `domain_kernel.py`'s own docstring. A real, CEFR-independent difficulty-tier type is future work, deferred because one spike is not two use cases. |
| `InterventionStrategy.MORPHOLOGY_DECOMPOSITION`, `.CONTEXT_VARIATION` | **Language-flavored names, not moved** | "Morphology" (word-part decomposition) and its vocabulary framing don't transfer cleanly; the spike never selects either (its confusion/prerequisite cases route to `ISOLATE`/`CONTRAST` and `PREREQUISITE_PATH`). Left as-is — no evidence this phase produces that they need to change. |
| `InterventionStrategy.ISOLATE`, `.CONTRAST`, `.PREREQUISITE_PATH`, `.PRODUCTION_PRACTICE`, `.ACQUISITION_RESTART` | **Keep, generic** | The spike's confusion pair stages to `ISOLATE` first (#185 TODO 1's isolate-before-contrast policy — `CONTRAST` only follows a recorded-effective prior `ISOLATE` plan for the same pair, which this spike does not fabricate), its prerequisite pair maps to `PREREQUISITE_PATH` — both through the unmodified `plan_intervention()`/`_STRATEGY_FOR_CATEGORY` — no changes needed. |
| `InterventionStrategy.SPATIAL_ANCHOR`, `.MNEMONIC_REPLACEMENT` | **Not evaluated** | Never auto-selected today even for vocabulary (SPATIAL_ANCHOR) or tied to `PhoneticInterferenceRule` (MNEMONIC_REPLACEMENT), which this phase already ruled language-specific above. Out of scope. |
| `intervention_efficacy.py` (`InterventionObservation`, `estimate_efficacy`) | **Keep, already generic — no changes made or needed** | Already parameterized by `item_class: str` and `language: str` as plain strings, not vocabulary types. The spike's delayed-outcome test uses it completely unmodified with `item_class="software_concept"`, `language="n/a"`. This is the cleanest "already done" finding in the audit. |
| FSRS scheduler (`spaced_repetition.py`) | **Keep, already generic — confirmed, not touched** | Operates purely on `ReviewState` (interval, stability, due date); nothing in it reads a word, a language, or a CEFR level. Not exercised by the spike (which does not model long-term scheduling), but nothing about it would need to change to be exercised. |

## TODO 1: the extension contract

`app/domain/services/domain_kernel.py` adds five `Protocol` classes — the
same "a versioned protocol other code depends on" shape `AIProvider`
already establishes — each answering exactly one of TODO 1's five
questions: `ItemProvider` ("what is an item"), `AnswerEvaluator` ("what
counts as a correct answer"), `PrerequisiteEvidenceSource` ("what evidence
supports a prerequisite relationship"), `SimilarityCandidateSource` ("what
makes two items similar/confusable"), and `InterventionContentSource`
("what intervention content looks like").

`diagnosis_engine.py` and `intervention_planning.py` are not imported by
this module for writing, only for reading their closed catalogs
(`InterventionStrategy`) to validate against. Every value shape an
extension can return — `AnswerEvaluation`, `PrerequisiteEvidence`,
`SimilarityCandidate`, `InterventionContent` — carries evidence plus a
confidence bounded to `[0, 1]`, validated in `__post_init__`, and none of
them has a field an extension could use to name a `DiagnosisCategory` or
choose an `InterventionStrategy` outside the existing catalog:
`InterventionContent.strategy` is checked against
`intervention_planning.InterventionStrategy` at construction time, and
`SimilarityCandidate.relation` is checked against the kernel's own closed
`KernelRelation` enum, not an open string. Persistence and tenant
isolation stay in `app.application`/`app.infrastructure`, untouched — no
kernel Protocol method accepts anything shaped like a repository, session,
or database handle (`tests/test_domain_kernel_contract.py` asserts this
structurally, by inspecting every Protocol method's parameters).

`tests/test_domain_kernel_contract.py` is the contract-test suite TODO 1
asks for: it tries to construct a content item attached to a fabricated
strategy, a similarity candidate carrying an unsupported relation, evidence
with an out-of-range confidence, and an id-less item — every one fails to
construct. That is the enforcement mechanism: rejection by construction,
not a runtime check a future change could accidentally bypass.

## TODO 2: the software-concepts spike

`app/domain/services/software_concepts_spike.py` models six items —
process, thread, stack, heap, authentication, authorization — with two
confusable pairs (process/thread, stack/heap) and one prerequisite pair
(authentication before authorization), implementing all five kernel
Protocols. `app/application/use_cases/domain_kernel_spike.py`'s
`RunSoftwareConceptSpikeUseCase` is the one real, gated entry point,
checking `RecallSettings.domain_kernel_spike_enabled` (default off,
persisted the same way every other `RecallSettings` flag is, migration
`20260807_36`) before running anything — but
deliberately **not** surfaced in `RecallSettingsResponse`/
`RecallSettingsUpdateRequest` or any router: there is nothing for an end
user to opt into, this is a developer/architecture flag, not a product
toggle.

`tests/test_domain_kernel_spike.py` runs the full evidence → diagnosis →
intervention → delayed-outcome cycle for the process/thread confusion pair
through the **unmodified** `diagnose()` and `plan_intervention()`
functions, plus `intervention_efficacy.estimate_efficacy()` for the
delayed-outcome measurement — all three imported from their existing
modules, none forked or subclassed. (`plan_intervention()` stages a fresh
confusion diagnosis to `ISOLATE`, not `CONTRAST` — #185 TODO 1's own
policy, unrelated to this phase — and the spike test asserts that real
behavior rather than the `CONTRAST`-only mapping an earlier draft of this
phase was written against.) It also demonstrates a second
diagnosis category (`WEAK_ACQUISITION`, for repeated stack/heap failure
with no prior recall) and the prerequisite pair (`MISSING_PREREQUISITE`
for authorization before authentication is solid), documenting the real
friction described below rather than hiding it.

## Cross-domain safety boundary (TODO 4)

"Learning diagnosis" is a LensWord product term for a pattern found in a
learner's own recall history — it is not, and must never be presented as,
a clinical, psychological, legal, or professional diagnosis in any sense
those words carry outside this product, regardless of which domain a
future pack targets. Concretely:

- A domain pack must not claim to detect a medical condition, a legal
  liability, a mental-health state, or any other professionally regulated
  determination, even if its item catalog is drawn from that field (a
  "medical terminology" vocabulary pack teaches recall of medical *terms*;
  it does not diagnose the learner or anyone else).
- `DiagnosisCategory`'s closed taxonomy stays scoped to recall-mechanism
  causes (forgetting, confusion, missing prerequisite, modality gap,
  context lock, weak acquisition) — a future domain pack cannot add a
  category, by the same "impossible by construction" mechanism TODO 1's
  contract tests verify, so a pack cannot introduce a clinical-sounding
  outcome even if it wanted to.
- Any domain whose subject matter could be mistaken for professional
  advice (medicine, law) needs its own explicit, domain-specific
  disclaimer at the UI layer before it ships — this ADR does not authorize
  skipping that; it only guarantees the diagnosis *kernel* itself cannot
  manufacture a professional claim.

No domain pack beyond the software-concepts spike exists in this codebase,
so this section is a boundary recorded ahead of need, the same way ADR
0007's observability rules were recorded before #182 built the tables they
govern.

## TODO 3: domain-pack manifest shape, not a loader

`DomainPackManifest` in `domain_kernel.py` is a real, validated dataclass —
`pack_id`, `display_name`, `schema_version`, `kernel_contract_version`,
`supported_relations` (must be `KernelRelation` members),
`content_sources` (bounded names, never a path or URL — no arbitrary
executable plugins), and `requires_permission_review` (defaults `True`).
`software_concepts_spike.py` fills one in for itself
(`SOFTWARE_CONCEPT_PACK_MANIFEST`) purely as a demonstration that the shape
is usable, not because anything loads or registers it.

**No loader, installer, or registry is built in this phase**, on purpose.
TODO 3 itself scopes this down explicitly given the spike is hardcoded, not
a real plugin system, and building install/permission-review machinery for
a manifest type nothing yet needs to load would be exactly the speculative
abstraction TODO 0 warns against. A second real domain pack is the trigger
for that work, not this one.

## TODO 5: go/no-go

**Go on the kernel abstraction. No-go on productizing multi-domain
support beyond this spike, for now.**

The honest, mixed result the issue asked for:

**Cleaner than predicted — the confusion path.** `EXACT_CONFUSION`,
`FORGETTING`, and `WEAK_ACQUISITION` all worked through
`diagnose()`/`plan_intervention()` with **zero** changes to either
function, using real (not fabricated) evidence: a genuine confusion pair,
genuine repeated-failure patterns. `intervention_efficacy.py` needed zero
changes and already took a plain `item_class: str` — it was more generic
than the audit initially assumed before reading it closely. This is the
strongest evidence the boundary works.

**Messier than predicted — the prerequisite path.**
`MissingPrerequisiteRule`'s only real evidence source,
`KnowledgeGraph.prerequisites()`, was built assuming two things vocabulary
always has and a software-concept pack does not natively have: a CEFR
level string, and *some* edge (of any type) already connecting the two
items. The spike's `PrerequisiteEvidenceSource` adapter works around both
— borrowing the CEFR ordinal strings as a difficulty-tier stand-in, and
synthesizing a `TOPIC` edge purely so `prerequisites()` considers the pair
"connected" at all — rather than either being a clean, purpose-built hook.
That is a genuine weak point the original TODO 0 prediction ("CEFR needs
an adapter") undersold slightly: it is not just CEFR that is coupled, the
*connectivity* mechanism is too.

**No core diagnosis/intervention conditionals were added.** `grep -n
'if domain' app/domain/services/diagnosis_engine.py
app/domain/services/intervention_planning.py` returns nothing — the hard
constraint the issue's success metrics named. Every domain-specific
decision lives in `domain_kernel.py`/`software_concepts_spike.py`, not in
either engine file.

**Why no-go on productizing:** one spike with six hardcoded items and no
real user demand is not evidence of reuse at scale — it is evidence the
*shape* of reuse is plausible for confusion/forgetting-style diagnoses and
requires real design work (a first-class prerequisite relation, a
difficulty-tier concept independent of CEFR) before a prerequisite-heavy
domain would be comfortable. Building a loader, an installer, or a second
real domain pack now would be exactly the "continue only if the second
domain reuses most of the core without weakening the vocabulary product"
bar the issue sets — a bar this single, non-representative spike cannot
clear on its own. The correct next step, if one ever arrives, is a second
*real* domain with real users asking for it, not a third internal spike.

## Consequences

### Positive

- The vocabulary product's diagnosis/intervention/efficacy code is
  unmodified by this phase — every existing test in
  `test_diagnosis_engine.py`, `test_intervention_planning.py`,
  `test_intervention_efficacy.py` continues to pass unchanged.
- A future contributor evaluating a second real domain has a concrete
  worked example (the spike) and an honest account of where the
  abstraction held and where it didn't, rather than a green-field guess.
- The extension contract's "impossible by construction" validation means
  a careless or adversarial domain pack cannot introduce an unsupported
  diagnosis category or strategy without a `ValueError` at construction
  time, well before any evidence reaches `diagnose()`.

### Negative

- `KnowledgeGraph.prerequisites()`'s CEFR/connectivity coupling remains
  unfixed — a real prerequisite-heavy non-language domain would hit the
  same friction this spike worked around, not a clean hook.
- `DiagnosisContext.word_id`/`KnowledgeGraph` node ids staying `int`-typed
  means every domain pack must mint and track its own stable integer id
  space (`KernelItem.numeric_id`) rather than using its own natural string
  keys directly.

## Verification

`tests/test_domain_kernel_contract.py` (24 cases combined with the spike
suite) enforces TODO 1's rejection requirements. `tests/test_domain_kernel_spike.py`
runs the full evidence → diagnosis → intervention → delayed-outcome cycle
TODO 2 requires, plus the prerequisite-path and flag-gating cases.
`domain_kernel.py` and `software_concepts_spike.py` are pure domain
modules under `app/domain/services/`, automatically covered by
`tests/test_diagnosis_architecture_boundary.py`'s framework-import scan —
no changes were needed to that test's scope, since it already walks the
whole `app/domain` tree.

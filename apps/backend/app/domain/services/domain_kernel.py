"""Domain-neutral extension contract for the diagnosis kernel (#180, #189).

This module is an additive abstraction layer, not a rewrite. It does not
touch `diagnosis_engine.py` or `intervention_planning.py` — both stay
exactly what they were before this phase: the vocabulary product's own
rules and strategy catalog. What this module adds is a way for a *different*
domain (software concepts, medicine, law, ...) to describe its own items,
correctness, prerequisite evidence, similarity evidence, and intervention
content well enough that `diagnose()` and `plan_intervention()` can run
against it unmodified, via the adapter functions below.

The extension points are five `Protocol` classes, the same "a versioned
protocol other code depends on" pattern `AIProvider`
(`app/domain/services/ai_provider.py`) already uses for the AI boundary.
Each answers exactly one question TODO 1 named:

- `ItemProvider` — what is an item.
- `AnswerEvaluator` — what counts as a correct answer.
- `PrerequisiteEvidenceSource` — what evidence supports a prerequisite
  relationship.
- `SimilarityCandidateSource` — what makes two items similar/confusable.
- `InterventionContentSource` — what intervention content looks like.

Extensions never diagnose. Every value an extension can hand back is
evidence plus a bounded confidence in [0, 1] (`DiagnosisEvidence.weight`'s
own scale) — never a `DiagnosisCategory`, never an `InterventionStrategy`
chosen freely, never a repository or session. `diagnose()`'s closed rule
set is the only thing that ever produces a category; `plan_intervention()`'s
closed catalog is the only thing that ever produces a strategy;
`InterventionContent` below can only be constructed for a strategy that
already exists in that catalog. This is "impossible by construction", not
a runtime permission check — `tests/test_domain_kernel_contract.py` proves
it by trying to build the disallowed shapes and watching them fail to
construct at all.

See `docs/adr/0009-domain-neutral-kernel.md` for the keep/move/adapt audit
this module is built from, the cross-domain safety boundary (a "learning
diagnosis" is not a clinical, legal, or professional diagnosis, in any
domain a future pack targets), and the honest go/no-go finding from
building the one spike this phase ships (#189 TODO 2,
`app/domain/services/software_concepts_spike.py`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Protocol

from app.domain.services.diagnosis_contracts import LearningObservation
from app.domain.services.diagnosis_engine import DiagnosisContext
from app.domain.services.intervention_planning import InterventionStrategy
from app.domain.services.knowledge_graph import KnowledgeEdge, KnowledgeGraph, Relation, WordNode
from app.domain.value_objects import ReviewOutcome, ReviewState, SessionMode

# Bumped when a Protocol's method signature or a value type below changes
# meaning — the same convention `RULES_VERSION`/`POLICY_VERSION` already use
# for their own closed catalogs. A `DomainPackManifest` (TODO 3) names the
# version it was written against so a future loader can tell a pack apart
# from one written for an older kernel shape, even though no loader exists
# yet to act on the difference.
KERNEL_CONTRACT_VERSION = 1


def _require_unit_interval(value: float, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be in [0, 1], got {value}")


def _require_nonempty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class KernelItem:
    """An item as the kernel sees it — "what is an item" (TODO 1).

    `numeric_id` exists because `DiagnosisContext.word_id` and
    `KnowledgeGraph`'s node/edge ids are typed `int` (a real TODO 0 finding:
    the "generic" core is still keyed by a numeric primary key the
    vocabulary product's own database assigns, not an opaque id). Rather
    than widen that type across the core for one spike, the kernel asks
    every domain pack to bring a stable integer of its own — the same way
    the vocabulary product's `Word.id` is stable, just owned by a different
    table.
    """

    item_id: str
    numeric_id: int
    label: str
    # A CEFR-ordinal string ("A1".."C2") if this pack wants
    # `KnowledgeGraph.prerequisites()` to compare it against another item's
    # tier — see `_prerequisite_edges` below for why this is a borrowed
    # encoding, not a real difficulty-tier concept, and why it stays that
    # way in this phase.
    difficulty_tier: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.item_id, "KernelItem.item_id")
        _require_nonempty(self.label, "KernelItem.label")
        if self.numeric_id <= 0:
            raise ValueError(f"KernelItem.numeric_id must be positive, got {self.numeric_id}")


class KernelRelation(str, Enum):
    """How the kernel is told two items relate — deliberately smaller than
    `knowledge_graph.Relation`: SYNONYM/ANTONYM/COLLOCATION describe lexical
    facts about words, not a shape every domain has an equivalent of.
    CONFUSABLE and RELATED are the two that generalize."""

    CONFUSABLE = "confusable"
    RELATED = "related"


_KERNEL_TO_GRAPH_RELATION: dict[KernelRelation, Relation] = {
    KernelRelation.CONFUSABLE: Relation.CONFUSED_WITH,
    KernelRelation.RELATED: Relation.TOPIC,
}


@dataclass(frozen=True, slots=True)
class AnswerEvaluation:
    """"What counts as a correct answer" (TODO 1) — evidence plus the
    evaluator's own confidence in its correctness judgement, never a
    diagnosis. An exact-match evaluator is always fully confident; a fuzzy
    or OCR-backed one might not be."""

    correct: bool
    normalized_response: str | None
    confidence: float

    def __post_init__(self) -> None:
        _require_unit_interval(self.confidence, "AnswerEvaluation.confidence")


@dataclass(frozen=True, slots=True)
class PrerequisiteEvidence:
    """"What evidence supports a prerequisite relationship" (TODO 1) —
    named by item id, with a confidence and a human rationale, never a
    `MISSING_PREREQUISITE` diagnosis itself."""

    prerequisite_item_id: str
    confidence: float
    rationale: str

    def __post_init__(self) -> None:
        _require_nonempty(self.prerequisite_item_id, "PrerequisiteEvidence.prerequisite_item_id")
        _require_nonempty(self.rationale, "PrerequisiteEvidence.rationale")
        _require_unit_interval(self.confidence, "PrerequisiteEvidence.confidence")


@dataclass(frozen=True, slots=True)
class SimilarityCandidate:
    """"What makes two items similar/confusable" (TODO 1). `relation` is
    restricted to `KernelRelation` by construction — an extension cannot
    smuggle an arbitrary string (a fabricated diagnosis category, for
    instance) through this field and have it survive to become a graph
    edge; `__post_init__` rejects it before it exists."""

    other_item_id: str
    relation: KernelRelation
    occurrences: int
    confidence: float
    rationale: str

    def __post_init__(self) -> None:
        _require_nonempty(self.other_item_id, "SimilarityCandidate.other_item_id")
        _require_nonempty(self.rationale, "SimilarityCandidate.rationale")
        _require_unit_interval(self.confidence, "SimilarityCandidate.confidence")
        if self.occurrences < 1:
            raise ValueError(f"SimilarityCandidate.occurrences must be >= 1, got {self.occurrences}")
        if not isinstance(self.relation, KernelRelation):
            raise ValueError(
                f"SimilarityCandidate.relation must be a KernelRelation member, got {self.relation!r}"
            )


@dataclass(frozen=True, slots=True)
class InterventionContent:
    """"What intervention content looks like" (TODO 1). `strategy` must
    already be a member of `intervention_planning.InterventionStrategy` —
    the closed catalog that module owns — checked in `__post_init__` so a
    content source cannot invent a tenth strategy (a "refer to a
    professional" content item, say) merely by writing one to this field.
    This module reads that catalog; it never adds to it."""

    strategy: str
    item_id: str
    prompt: str

    def __post_init__(self) -> None:
        _require_nonempty(self.item_id, "InterventionContent.item_id")
        _require_nonempty(self.prompt, "InterventionContent.prompt")
        try:
            InterventionStrategy(self.strategy)
        except ValueError as exc:
            raise ValueError(
                f"InterventionContent.strategy must be a member of the closed "
                f"InterventionStrategy catalog, got {self.strategy!r}"
            ) from exc


class ItemProvider(Protocol):
    def get_item(self, item_id: str) -> KernelItem: ...


class AnswerEvaluator(Protocol):
    def evaluate(self, item_id: str, response: str) -> AnswerEvaluation: ...


class PrerequisiteEvidenceSource(Protocol):
    def prerequisite_evidence(self, item_id: str) -> tuple[PrerequisiteEvidence, ...]: ...


class SimilarityCandidateSource(Protocol):
    def similarity_candidates(self, item_id: str) -> tuple[SimilarityCandidate, ...]: ...


class InterventionContentSource(Protocol):
    def content_for(
        self, *, strategy: str, item_id: str, item_label: str, other_label: str | None = None
    ) -> InterventionContent: ...


def observation_from_evaluation(
    *,
    observation_id: str,
    item: KernelItem,
    user_id: int,
    evaluation: AnswerEvaluation,
    observed_at: datetime,
    attempted_answer: str | None = None,
) -> LearningObservation:
    """Adapts one `AnswerEvaluator` result into the exact
    `LearningObservation` shape `diagnosis_engine.py` already reads —
    `word_id`/`term` stay the field names they are (TODO 0: not renamed
    without a second use case), populated from `KernelItem` instead of a
    vocabulary word."""
    return LearningObservation(
        observation_id=observation_id,
        word_id=item.numeric_id,
        user_id=user_id,
        outcome=ReviewOutcome.CORRECT if evaluation.correct else ReviewOutcome.INCORRECT,
        session_mode=SessionMode.STANDARD,
        observed_at=observed_at,
        attempted_answer=attempted_answer if attempted_answer is not None else evaluation.normalized_response,
    )


def _prerequisite_edges(
    item: KernelItem,
    catalog: Mapping[str, KernelItem],
    prerequisite_source: PrerequisiteEvidenceSource | None,
) -> list[KnowledgeEdge]:
    """`KnowledgeGraph.prerequisites()` finds a prerequisite by combining
    two signals that were both built for vocabulary: an edge connecting the
    two items (of *any* relation type — there is no dedicated "is a
    prerequisite of" relation) and a lower CEFR-ordinal `cefr_level` on the
    easier one. Neither is a clean prerequisite-evidence hook.

    This function reuses both as they exist today rather than adding a
    first-class prerequisite relation or an independent difficulty-tier
    ordering to the core graph: TOPIC ("these two are related") is a
    genuinely generic relation two prerequisite-linked items really can
    share, and the CEFR-ordinal strings on `KernelItem.difficulty_tier` are
    a borrowed encoding, not a real language level. Both are recorded as
    friction in `docs/adr/0009-domain-neutral-kernel.md`'s go/no-go section
    — a single spike is not enough evidence to justify fixing either
    (TODO 0's own rule against speculative abstraction).
    """
    if prerequisite_source is None:
        return []
    edges: list[KnowledgeEdge] = []
    for evidence in prerequisite_source.prerequisite_evidence(item.item_id):
        other = catalog.get(evidence.prerequisite_item_id)
        if other is None:
            continue
        edges.append(
            KnowledgeEdge(
                source_id=min(item.numeric_id, other.numeric_id),
                target_id=max(item.numeric_id, other.numeric_id),
                relation=Relation.TOPIC,
                evidence=evidence.rationale,
                occurrences=1,
            )
        )
    return edges


def build_diagnosis_context(
    *,
    item: KernelItem,
    user_id: int,
    observations: tuple[LearningObservation, ...],
    catalog: Mapping[str, KernelItem],
    similarity_source: SimilarityCandidateSource | None = None,
    prerequisite_source: PrerequisiteEvidenceSource | None = None,
    review_state: ReviewState | None = None,
) -> DiagnosisContext:
    """The seam TODO 1 asks for: kernel-shaped inputs in, the exact
    `DiagnosisContext` `diagnose()` already accepts out. Nothing here calls
    `diagnose()` itself, and nothing in `diagnosis_engine.py` changes to
    make this possible — nodes and edges are built the same way any other
    `KnowledgeGraph` caller builds them (see
    `app/application/use_cases/knowledge_graph.py`'s `nodes_for`), just
    from `KernelItem`/`SimilarityCandidate`/`PrerequisiteEvidence` instead
    of `Word` rows.
    """
    nodes = [
        WordNode(word_id=candidate.numeric_id, term=candidate.label, cefr_level=candidate.difficulty_tier)
        for candidate in catalog.values()
    ]

    edges: list[KnowledgeEdge] = []
    if similarity_source is not None:
        for candidate in similarity_source.similarity_candidates(item.item_id):
            other = catalog.get(candidate.other_item_id)
            if other is None:
                continue
            edges.append(
                KnowledgeEdge(
                    source_id=min(item.numeric_id, other.numeric_id),
                    target_id=max(item.numeric_id, other.numeric_id),
                    relation=_KERNEL_TO_GRAPH_RELATION[candidate.relation],
                    evidence=candidate.rationale,
                    occurrences=candidate.occurrences,
                )
            )
    edges.extend(_prerequisite_edges(item, catalog, prerequisite_source))

    graph = KnowledgeGraph(nodes, edges)
    return DiagnosisContext(
        word_id=item.numeric_id,
        user_id=user_id,
        term=item.label,
        observations=observations,
        graph=graph,
        review_state=review_state or ReviewState.initial(),
    )


@dataclass(frozen=True, slots=True)
class DomainPackManifest:
    """The declared SHAPE of a domain pack (#189 TODO 3) — a real, tested
    type, not a loader. No installer or plugin runtime exists in this
    codebase, and none is built by this phase: that is deliberately
    deferred until a second real domain justifies it (TODO 0's own rule
    against speculative abstraction with no second use case). v1's own
    constraint — "no arbitrary executable plugins, declarative packs and
    trusted adapters only" — is reflected in `content_sources` being bound
    names a trusted adapter recognizes, never a path or URL a pack supplies
    code from.
    """

    pack_id: str
    display_name: str
    schema_version: int
    kernel_contract_version: int
    supported_relations: tuple[KernelRelation, ...]
    content_sources: tuple[str, ...]
    # No pack installs itself sight unseen — this field exists so a future
    # loader (not built here) has somewhere to record that a human looked
    # at what a pack claims before it runs, the same "explicit installation/
    # permission review" TODO 3 asks for.
    requires_permission_review: bool = True

    def __post_init__(self) -> None:
        _require_nonempty(self.pack_id, "DomainPackManifest.pack_id")
        _require_nonempty(self.display_name, "DomainPackManifest.display_name")
        if self.schema_version < 1:
            raise ValueError("DomainPackManifest.schema_version must be >= 1")
        if self.kernel_contract_version < 1:
            raise ValueError("DomainPackManifest.kernel_contract_version must be >= 1")
        if not self.supported_relations:
            raise ValueError("DomainPackManifest.supported_relations must name at least one relation")
        if any(not isinstance(r, KernelRelation) for r in self.supported_relations):
            raise ValueError("DomainPackManifest.supported_relations must only contain KernelRelation members")
        if not self.content_sources:
            raise ValueError("DomainPackManifest.content_sources must name at least one source")

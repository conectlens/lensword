"""Software-concepts domain-kernel spike (#180, #189 TODO 2).

Six software concepts — process, thread, stack, heap, authentication,
authorization — with a couple of deliberately confusable pairs (process/
thread, stack/heap) and one prerequisite pair (authentication before
authorization), run through the SAME `diagnose()`/`plan_intervention()`
functions the vocabulary product uses, adapted through
`app.domain.services.domain_kernel`. Nothing in either of those two
functions changes to make this possible.

Not a real domain pack: no loader, no persistence, no HTTP surface (#189
TODO 3 explains why none of those are built yet). The one real entry point
that actually runs this spike is
`app.application.use_cases.domain_kernel_spike.RunSoftwareConceptSpikeUseCase`,
gated behind `RecallSettings.domain_kernel_spike_enabled` (default off).
This module itself is pure fixture data plus the five kernel Protocol
implementations — importable and unit-testable with zero I/O, like every
other module in `app/domain/services/`.

This is an architecture proof, not a LensWord product feature: it never
implies clinical, professional, or educational-assessment competence in
"process" or "authorization" any more than the vocabulary product's own
diagnoses imply one in Spanish — see `docs/adr/0009-domain-neutral-kernel.md`'s
safety-boundary note.
"""
from __future__ import annotations

from app.domain.services.domain_kernel import (
    AnswerEvaluation,
    DomainPackManifest,
    InterventionContent,
    KERNEL_CONTRACT_VERSION,
    KernelItem,
    KernelRelation,
    PrerequisiteEvidence,
    SimilarityCandidate,
)

# Reserved id space starting well above any real Word.id this build could
# have — this spike never reads or writes the words table, but the kernel
# still requires a stable positive int per item (see KernelItem's own
# docstring for why), so these are chosen to be obviously not real data.
_PROCESS = KernelItem(item_id="process", numeric_id=900_001, label="process")
_THREAD = KernelItem(item_id="thread", numeric_id=900_002, label="thread")
_STACK = KernelItem(item_id="stack", numeric_id=900_003, label="stack")
_HEAP = KernelItem(item_id="heap", numeric_id=900_004, label="heap")
# CEFR-ordinal stand-ins, not real language levels — see
# `domain_kernel._prerequisite_edges` for why `KnowledgeGraph.prerequisites()`
# needs these strings specifically to compare "authentication" as easier
# than "authorization".
_AUTHENTICATION = KernelItem(item_id="authentication", numeric_id=900_005, label="authentication", difficulty_tier="A1")
_AUTHORIZATION = KernelItem(item_id="authorization", numeric_id=900_006, label="authorization", difficulty_tier="A2")

CATALOG: dict[str, KernelItem] = {
    concept.item_id: concept
    for concept in (_PROCESS, _THREAD, _STACK, _HEAP, _AUTHENTICATION, _AUTHORIZATION)
}


class SoftwareConceptItemProvider:
    """"What is an item" (TODO 1) for this domain: one of the six concepts
    above, looked up by its own id."""

    def get_item(self, item_id: str) -> KernelItem:
        return CATALOG[item_id]


class ExactLabelAnswerEvaluator:
    """"What counts as a correct answer" (TODO 1): the response matches the
    item's own label, case-insensitively. No fuzzy matching, so confidence
    is always 1.0 — the same certainty an exact string comparison earns in
    the vocabulary product's own typed-answer check."""

    def evaluate(self, item_id: str, response: str) -> AnswerEvaluation:
        item = CATALOG[item_id]
        normalized = response.strip().casefold()
        correct = normalized == item.label.strip().casefold()
        return AnswerEvaluation(correct=correct, normalized_response=normalized, confidence=1.0)


# item_id -> (confused-with item_id, how many times it recurred). A real
# domain pack would derive this from its own mistake history, the way #134
# derives CONFUSED_WITH edges for vocabulary from MistakeEvent rows; this
# spike hardcodes the outcome of that derivation instead of reimplementing
# it for six fixed items.
_CONFUSION_PAIRS: dict[str, tuple[str, int]] = {
    "process": ("thread", 2),
    "thread": ("process", 2),
    "stack": ("heap", 2),
    "heap": ("stack", 2),
}


class StaticConfusionPairs:
    """"What makes two items similar/confusable" (TODO 1): a fixed
    confusion pair per item, each reported with evidence and a bounded
    confidence — never as a `DiagnosisCategory` itself."""

    def similarity_candidates(self, item_id: str) -> tuple[SimilarityCandidate, ...]:
        pair = _CONFUSION_PAIRS.get(item_id)
        if pair is None:
            return ()
        other_id, occurrences = pair
        return (
            SimilarityCandidate(
                other_item_id=other_id,
                relation=KernelRelation.CONFUSABLE,
                occurrences=occurrences,
                confidence=0.9,
                rationale=f"learners repeatedly answer '{other_id}' when asked about '{item_id}'",
            ),
        )


class AuthPrerequisiteSource:
    """"What evidence supports a prerequisite relationship" (TODO 1):
    authorization decisions presuppose the caller is already authenticated,
    so authentication is reported as authorization's prerequisite."""

    def prerequisite_evidence(self, item_id: str) -> tuple[PrerequisiteEvidence, ...]:
        if item_id != "authorization":
            return ()
        return (
            PrerequisiteEvidence(
                prerequisite_item_id="authentication",
                confidence=0.8,
                rationale="authorization decisions assume the caller is already authenticated",
            ),
        )


# One deterministic template per strategy this spike actually reaches.
# Strategies this spike never triggers fall back to a generic prompt rather
# than raising — a content source abstaining from specificity is a normal
# outcome, matching the rest of this epic's "prefer abstention" bias.
_CONTENT_TEMPLATES: dict[str, str] = {
    "contrast": "Compare {label} with {other}, and name one concrete difference between them.",
    "prerequisite_path": "Before continuing with {label}, make sure {other} is solid first.",
    "acquisition_restart": "Restart {label} from a clean example, without leaning on {other}.",
}


class TemplatedContentSource:
    """"What intervention content looks like" (TODO 1): a deterministic
    string template, not a model call — the same "no AI in the diagnosis/
    intervention loop" boundary ADR 0007 draws for the vocabulary product.
    This spike does not exercise responsibility 3 (AI explanation) at all."""

    def content_for(
        self, *, strategy: str, item_id: str, item_label: str, other_label: str | None = None
    ) -> InterventionContent:
        template = _CONTENT_TEMPLATES.get(strategy, "Practice {label} again, deliberately.")
        prompt = template.format(label=item_label, other=other_label or "the concept it's confused with")
        return InterventionContent(strategy=strategy, item_id=item_id, prompt=prompt)


# TODO 3's manifest SHAPE, filled in for this one spike — not registered
# anywhere, since no loader exists to register it with.
SOFTWARE_CONCEPT_PACK_MANIFEST = DomainPackManifest(
    pack_id="software-concepts-spike",
    display_name="Software Concepts (developer spike)",
    schema_version=1,
    kernel_contract_version=KERNEL_CONTRACT_VERSION,
    supported_relations=(KernelRelation.CONFUSABLE, KernelRelation.RELATED),
    content_sources=("static_template_fixture",),
    requires_permission_review=True,
)

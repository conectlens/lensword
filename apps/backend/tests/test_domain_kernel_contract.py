"""Contract tests for the domain-neutral kernel (#189 TODO 1).

TODO 1's own verify clause: "contract tests reject extensions that bypass
application use cases or emit unsupported diagnosis types." Every test
here tries to build a shape a malicious or merely careless extension might
attempt, and asserts it cannot be constructed at all — "impossible by
construction", not a runtime permission check that a bug could skip.
"""
from __future__ import annotations

import inspect

import pytest

from app.domain.services.domain_kernel import (
    AnswerEvaluation,
    AnswerEvaluator,
    DomainPackManifest,
    InterventionContent,
    InterventionContentSource,
    ItemProvider,
    KERNEL_CONTRACT_VERSION,
    KernelItem,
    KernelRelation,
    PrerequisiteEvidence,
    PrerequisiteEvidenceSource,
    SimilarityCandidate,
    SimilarityCandidateSource,
)
from app.domain.services.intervention_planning import InterventionStrategy

_KERNEL_PROTOCOLS = (
    ItemProvider,
    AnswerEvaluator,
    PrerequisiteEvidenceSource,
    SimilarityCandidateSource,
    InterventionContentSource,
)


# --- An extension can never emit a diagnosis or strategy directly ----------


def test_intervention_content_rejects_a_strategy_outside_the_closed_catalog():
    """A content source that tries to attach content to a strategy the
    intervention-planning catalog does not own — e.g. something implying a
    clinical referral — cannot be constructed."""
    with pytest.raises(ValueError):
        InterventionContent(strategy="refer_to_a_clinician", item_id="thread", prompt="See a professional.")


def test_intervention_content_accepts_every_real_strategy():
    # The flip side: nothing about the validation is overzealous — every
    # strategy the real catalog actually has is constructible.
    for strategy in InterventionStrategy:
        content = InterventionContent(strategy=strategy.value, item_id="x", prompt="practice")
        assert content.strategy == strategy.value


def test_similarity_candidate_rejects_a_relation_outside_the_kernel_taxonomy():
    """A rogue extension cannot smuggle an arbitrary string (say, a
    fabricated diagnosis category) through `relation` and have it survive
    into a graph edge — only real `KernelRelation` members construct."""

    class _FakeRelation(str):
        """Looks like a string a careless caller might pass instead of a
        real KernelRelation member."""

    with pytest.raises(ValueError):
        SimilarityCandidate(
            other_item_id="process",
            relation=_FakeRelation("secretly_exact_confusion"),
            occurrences=3,
            confidence=0.9,
            rationale="looks legitimate",
        )


# --- Evidence and uncertainty only — never a free-form diagnosis -----------


@pytest.mark.parametrize(
    "build",
    [
        lambda: AnswerEvaluation(correct=True, normalized_response="thread", confidence=1.5),
        lambda: AnswerEvaluation(correct=True, normalized_response="thread", confidence=-0.1),
    ],
)
def test_answer_evaluation_confidence_is_bounded(build):
    with pytest.raises(ValueError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: PrerequisiteEvidence(prerequisite_item_id="authentication", confidence=2.0, rationale="r"),
        lambda: PrerequisiteEvidence(prerequisite_item_id="", confidence=0.5, rationale="r"),
        lambda: PrerequisiteEvidence(prerequisite_item_id="authentication", confidence=0.5, rationale=""),
    ],
)
def test_prerequisite_evidence_is_bounded_and_never_empty(build):
    with pytest.raises(ValueError):
        build()


def test_similarity_candidate_confidence_and_occurrences_are_bounded():
    with pytest.raises(ValueError):
        SimilarityCandidate(
            other_item_id="process", relation=KernelRelation.CONFUSABLE,
            occurrences=0, confidence=0.5, rationale="r",
        )
    with pytest.raises(ValueError):
        SimilarityCandidate(
            other_item_id="process", relation=KernelRelation.CONFUSABLE,
            occurrences=1, confidence=1.1, rationale="r",
        )


def test_kernel_item_requires_a_positive_stable_id_and_a_label():
    with pytest.raises(ValueError):
        KernelItem(item_id="thread", numeric_id=0, label="thread")
    with pytest.raises(ValueError):
        KernelItem(item_id="", numeric_id=1, label="thread")
    with pytest.raises(ValueError):
        KernelItem(item_id="thread", numeric_id=1, label="")


# --- No channel to a repository, session, or persistence layer -------------


def test_kernel_protocols_never_accept_a_repository_session_or_db_handle():
    """"Keep persistence and tenant isolation in the core application"
    (TODO 1). An extension implementing one of these Protocols is only ever
    called with plain values — an id, a response string, a strategy name —
    never anything that could reach a database. This is a structural
    guarantee: no method on any kernel Protocol even has a parameter shaped
    like an I/O handle for an extension to receive and misuse."""
    forbidden_substrings = ("repo", "session", "db", "engine", "connection", "conn")
    for protocol in _KERNEL_PROTOCOLS:
        for name, member in vars(protocol).items():
            if name.startswith("_") or not callable(member):
                continue
            for param_name in inspect.signature(member).parameters:
                if param_name == "self":
                    continue
                lowered = param_name.lower()
                assert not any(bad in lowered for bad in forbidden_substrings), (
                    f"{protocol.__name__}.{name} exposes parameter {param_name!r}, "
                    "which looks like an I/O handle an extension should never receive"
                )


# --- DomainPackManifest (TODO 3): a real, validated shape, not a loader ----


def _manifest(**overrides) -> DomainPackManifest:
    fields = dict(
        pack_id="spike",
        display_name="Spike",
        schema_version=1,
        kernel_contract_version=KERNEL_CONTRACT_VERSION,
        supported_relations=(KernelRelation.CONFUSABLE,),
        content_sources=("static_fixture",),
    )
    fields.update(overrides)
    return DomainPackManifest(**fields)


def test_domain_pack_manifest_accepts_a_well_formed_pack():
    manifest = _manifest()
    assert manifest.requires_permission_review is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"pack_id": ""},
        {"display_name": ""},
        {"schema_version": 0},
        {"kernel_contract_version": 0},
        {"supported_relations": ()},
        {"content_sources": ()},
    ],
)
def test_domain_pack_manifest_rejects_malformed_declarations(overrides):
    with pytest.raises(ValueError):
        _manifest(**overrides)


def test_domain_pack_manifest_rejects_a_relation_outside_the_kernel_taxonomy():
    with pytest.raises(ValueError):
        _manifest(supported_relations=("synonym",))  # a knowledge_graph.Relation value, not a KernelRelation

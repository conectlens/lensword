"""Gathers context and runs the diagnosis engine for one word (#183).

The engine itself (`diagnosis_engine.py`) is pure — no repository, no I/O.
This is the one place that assembles the `DiagnosisContext` a real account
would produce and persists the result, mirroring how
`RecomputeKnowledgeEdgesForWordUseCase` (#203) is the seam between the pure
`build_edges()` function and real data.
"""
from __future__ import annotations

from app.application.use_cases.knowledge_graph import nodes_for
from app.domain.repositories import (
    DiagnosisRepository,
    KnowledgeEdgeRepository,
    LearningObservationRepository,
    WordRepository,
)
from app.domain.services.diagnosis_engine import DiagnosisContext, diagnose
from app.domain.services.knowledge_graph import KnowledgeGraph


class RunDiagnosisForWordUseCase:
    def __init__(
        self,
        word_repo: WordRepository,
        observation_repo: LearningObservationRepository,
        edge_repo: KnowledgeEdgeRepository,
        diagnosis_repo: DiagnosisRepository,
    ):
        self.word_repo = word_repo
        self.observation_repo = observation_repo
        self.edge_repo = edge_repo
        self.diagnosis_repo = diagnosis_repo

    def execute(self, user_id: int, word_id: int):
        word = self.word_repo.get_by_id(word_id)
        if word is None or word.group_id is None:
            return None

        # The graph needs every word the account owns (confusion and
        # prerequisite edges can name any of them), not just this one —
        # the same reasoning graph_for_user (#203) already applies to the
        # read endpoints.
        all_words = self.word_repo.list_all_for_user(user_id)
        nodes = nodes_for(all_words)
        graph = KnowledgeGraph(nodes, self.edge_repo.list_all_for_user(user_id))

        observations = self.observation_repo.list_for_word(user_id, word_id)
        context = DiagnosisContext(
            word_id=word_id,
            user_id=user_id,
            term=word.term,
            observations=tuple(observations),
            graph=graph,
            review_state=word.review_state,
        )
        result = diagnose(context)
        return self.diagnosis_repo.add(result)

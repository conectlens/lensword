"""Assembles a bounded `ConversationContext` (#194 TODO 2) from real
repositories — the I/O half of `app.domain.services.conversation_context`,
which stays pure. Reuses #185's `active_plans` (from
`app.application.use_cases.intervention`) rather than re-deriving "which
plan is still active" a second way.
"""
from __future__ import annotations

from app.application.use_cases.intervention import active_plans
from app.domain.entities import Word
from app.domain.exceptions import EntityNotFoundError
from app.domain.repositories import (
    CompanionSessionRepository,
    DiagnosisRepository,
    GroupRepository,
    InterventionRepository,
    WordRepository,
)
from app.domain.services.conversation_context import (
    MAX_ACTIVE_WORDS,
    MAX_CONFUSION_ITEMS,
    MAX_DUE_ITEMS,
    ActiveWordFact,
    ConfusionFact,
    ConversationContext,
    DueItemFact,
    SelectedInterventionFact,
    build_conversation_context,
)

# How many distinct words are even considered for confusion/intervention
# lookups — independent of (and at least as large as) the active/due caps,
# so every word that could appear in either bounded list still gets a
# chance to surface a confusion or intervention fact.
_MAX_CANDIDATE_WORDS = 15


class AssembleConversationContextUseCase:
    def __init__(
        self,
        session_repo: CompanionSessionRepository,
        word_repo: WordRepository,
        group_repo: GroupRepository,
        diagnosis_repo: DiagnosisRepository,
        intervention_repo: InterventionRepository,
    ):
        self.session_repo = session_repo
        self.word_repo = word_repo
        self.group_repo = group_repo
        self.diagnosis_repo = diagnosis_repo
        self.intervention_repo = intervention_repo

    def execute(self, user_id: int, session_id: str) -> ConversationContext:
        session = self.session_repo.get(user_id, session_id)
        if session is None:
            raise EntityNotFoundError("Companion session", session_id)

        words = self._scoped_words(user_id, session.group_id)
        due_words = self.word_repo.list_due_for_user(user_id, MAX_DUE_ITEMS, session.group_id, 0)
        active_words = [word for word in words if word.review_state.repetitions > 0][:MAX_ACTIVE_WORDS]

        candidate_ids: list[int] = []
        for word in [*due_words, *active_words]:
            if word.id is not None and word.id not in candidate_ids:
                candidate_ids.append(word.id)
            if len(candidate_ids) >= _MAX_CANDIDATE_WORDS:
                break

        confusion: list[ConfusionFact] = []
        best_intervention: SelectedInterventionFact | None = None
        best_planned_at = None
        for word_id in candidate_ids:
            if len(confusion) < MAX_CONFUSION_ITEMS:
                diagnosis = self.diagnosis_repo.latest_for_word(user_id, word_id)
                if diagnosis is not None and not diagnosis.is_abstention:
                    confusion.append(
                        ConfusionFact(
                            word_id=word_id,
                            outcome=diagnosis.outcome,
                            confidence=diagnosis.confidence,
                            sample_size=diagnosis.sample_size,
                        )
                    )

            plans = self.intervention_repo.list_plans_for_word(user_id, word_id)
            if not plans:
                continue
            outcomes = self.intervention_repo.list_outcomes_for_word(user_id, word_id)
            for plan in active_plans(plans, outcomes):
                if best_planned_at is None or plan.planned_at > best_planned_at:
                    best_planned_at = plan.planned_at
                    best_intervention = SelectedInterventionFact(
                        plan_id=plan.id,
                        word_id=plan.word_id,
                        strategy=plan.strategy,
                        diagnosis_outcome=plan.diagnosis_outcome,
                        rationale=plan.rationale,
                    )

        return build_conversation_context(
            session_id=session_id,
            goal=session.goal,
            active_words=[
                ActiveWordFact(
                    word_id=word.id or 0,
                    term=word.term,
                    target_language=word.target_language.value,
                    cefr_level=word.cefr_level,
                )
                for word in active_words
            ],
            due_items=[
                DueItemFact(word_id=word.id or 0, term=word.term, target_language=word.target_language.value)
                for word in due_words
            ],
            confusion=confusion,
            selected_intervention=best_intervention,
        )

    def _scoped_words(self, user_id: int, group_id: int | None) -> list[Word]:
        if group_id is not None:
            group = self.group_repo.get_by_id(group_id)
            if group is None or group.owner_id != user_id:
                return []
            return self.word_repo.list_by_group(group_id)
        words: list[Word] = []
        for group in self.group_repo.list_by_owner(user_id):
            words.extend(self.word_repo.list_by_group(group.id or 0))
        return words

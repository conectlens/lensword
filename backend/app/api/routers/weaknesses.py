"""What the learner keeps getting wrong (issue #134).

Read-only and scoped to the caller. There is no route for reading anyone
else's profile — a weakness profile is the most unflattering data the product
holds about a person, and the safest design is one where the question "can I
see someone else's?" has no endpoint to ask it of.
"""
from fastapi import APIRouter

from app.api.deps import CurrentUser, MistakeEventRepo, WordRepo
from app.api.schemas.weaknesses import (
    CategoryWeaknessResponse,
    ConfusedPairResponse,
    WeaknessProfileResponse,
)
from app.domain.services.weakness import (
    ErrorCategory,
    MistakeEvent,
    WeaknessProfileService,
)

router = APIRouter(prefix="/api/v1/me", tags=["weaknesses"])

# How many recent mistakes the profile is built from. Bounded because the
# aggregation happens in memory, and because a weakness from two years ago is
# not one the learner still has.
PROFILE_WINDOW = 1000


@router.get("/weaknesses", response_model=WeaknessProfileResponse)
def get_my_weaknesses(
    current_user: CurrentUser,
    mistake_repo: MistakeEventRepo,
    word_repo: WordRepo,
) -> WeaknessProfileResponse:
    rows = mistake_repo.list_for_user(current_user.id, limit=PROFILE_WINDOW)

    events = [
        MistakeEvent(
            user_id=row.user_id,
            word_id=row.word_id,
            # Stored as a string, so a value this build has no meaning for is a
            # data possibility rather than a programming error — an unreadable
            # row becomes UNKNOWN instead of failing the whole profile.
            category=_category(row.category),
            attempted_answer=row.attempted_answer,
            confused_with_word_id=row.confused_with_word_id,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]

    profile = WeaknessProfileService.build(events)

    # Terms are resolved only for the pairs actually reported — a handful —
    # rather than for every mistake loaded.
    terms: dict[int, str | None] = {}
    for pair in profile.confused_pairs:
        for word_id in (pair.word_id, pair.confused_with_word_id):
            if word_id not in terms:
                word = word_repo.get_by_id(word_id)
                terms[word_id] = word.term if word else None

    return WeaknessProfileResponse(
        total_mistakes=profile.total_mistakes,
        categories=[
            CategoryWeaknessResponse(
                category=c.category.value, occurrences=c.occurrences, share=round(c.share, 4)
            )
            for c in profile.categories
        ],
        confused_pairs=[
            ConfusedPairResponse(
                word_id=p.word_id,
                word_term=terms.get(p.word_id),
                confused_with_word_id=p.confused_with_word_id,
                confused_with_term=terms.get(p.confused_with_word_id),
                occurrences=p.occurrences,
            )
            for p in profile.confused_pairs
        ],
        insufficient_data=profile.insufficient_data,
    )


def _category(raw: str) -> ErrorCategory:
    try:
        return ErrorCategory(raw)
    except ValueError:
        return ErrorCategory.UNKNOWN

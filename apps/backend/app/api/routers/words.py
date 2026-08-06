from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    CurrentUser,
    GroupRepo,
    KnowledgeEdgeRepo,
    MistakeEventRepo,
    WordRepo,
    WordRevisionRepo,
)
from app.api.mappers import word_to_response
from app.api.schemas.vocabulary import (
    BulkWordEditRequest,
    BulkWordEditResponse,
    WordAssociationsUpdateRequest,
    WordCreateRequest,
    WordResponse,
    WordRevisionResponse,
    WordVerificationResponse,
)
from app.application.use_cases.vocabulary import (
    DeleteWordUseCase,
    GetWordUseCase,
    UpdateWordAssociationsUseCase,
    UpdateWordUseCase,
    WordInput,
)
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.services.ai_provenance import EditSource, is_ai_generated, verification_state
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/words", tags=["words"])


def _handle_common_errors(exc: Exception):
    if isinstance(exc, EntityNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    raise exc


@router.get("/{word_id}", response_model=WordResponse)
def get_word(word_id: int, current_user: CurrentUser, word_repo: WordRepo, group_repo: GroupRepo) -> WordResponse:
    try:
        word = GetWordUseCase(word_repo, group_repo).execute(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    return word_to_response(word)


@router.put("/{word_id}", response_model=WordResponse)
def update_word(
    word_id: int,
    payload: WordCreateRequest,
    current_user: CurrentUser,
    word_repo: WordRepo,
    group_repo: GroupRepo,
    revision_repo: WordRevisionRepo,
    edge_repo: KnowledgeEdgeRepo,
    mistake_repo: MistakeEventRepo,
) -> WordResponse:
    try:
        word = UpdateWordUseCase(word_repo, group_repo, revision_repo, edge_repo, mistake_repo).execute(
            current_user.id,
            word_id,
            WordInput(
                term=payload.term,
                target_language=payload.target_language,
                translations=payload.translations,
                example_sentence=payload.example_sentence,
                mnemonic=payload.mnemonic,
                category=payload.category,
                definition=payload.definition,
                part_of_speech=payload.part_of_speech,
                cefr_level=payload.cefr_level,
                pronunciation=payload.pronunciation,
                collocations=payload.collocations,
                tags=payload.tags,
                synonyms=payload.synonyms,
                antonyms=payload.antonyms,
                topics=payload.topics,
                ai_confidence=payload.ai_confidence,
                ai_provider=payload.ai_provider,
                ai_model=payload.ai_model,
            ),
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    return word_to_response(word)


@router.patch("/{word_id}/associations", response_model=WordResponse)
def update_associations(
    word_id: int,
    payload: WordAssociationsUpdateRequest,
    current_user: CurrentUser,
    word_repo: WordRepo,
    group_repo: GroupRepo,
    edge_repo: KnowledgeEdgeRepo,
    mistake_repo: MistakeEventRepo,
) -> WordResponse:
    try:
        word = UpdateWordAssociationsUseCase(word_repo, group_repo, edge_repo, mistake_repo).execute(
            current_user.id,
            word_id,
            add=[(e.kind, e.value) for e in payload.add],
            remove=[(e.kind, e.value) for e in payload.remove],
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)
    return word_to_response(word)


@router.delete("/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_word(word_id: int, current_user: CurrentUser, word_repo: WordRepo, group_repo: GroupRepo) -> None:
    try:
        DeleteWordUseCase(word_repo, group_repo).execute(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)


@router.get("/{word_id}/history", response_model=list[WordRevisionResponse])
def word_history(
    word_id: int,
    current_user: CurrentUser,
    word_repo: WordRepo,
    group_repo: GroupRepo,
    revision_repo: WordRevisionRepo,
) -> list[WordRevisionResponse]:
    """What the model-written fields on this card used to say.

    Ownership is checked first: the history of someone else's card describes
    their vocabulary, and reading it would be as much a disclosure as reading
    the card.
    """
    try:
        GetWordUseCase(word_repo, group_repo).execute(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)

    return [
        WordRevisionResponse(
            field=row.field,
            before_value=row.before_value,
            after_value=row.after_value,
            source=row.source,
            changed_at=row.changed_at,
        )
        for row in revision_repo.list_for_word(word_id)
    ]


@router.post("/{word_id}/verify", response_model=WordVerificationResponse)
def verify_word(
    word_id: int, current_user: CurrentUser, word_repo: WordRepo, group_repo: GroupRepo
) -> WordVerificationResponse:
    """Mark a model-written card as checked by a human.

    Refused for a card no model wrote: there is nothing to have verified, and
    letting the flag be set anyway would make "verified" mean two different
    things depending on the card.
    """
    try:
        word = GetWordUseCase(word_repo, group_repo).execute(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)

    if not is_ai_generated(word.ai_provider):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This card was not written by a model, so there is nothing to verify",
        )

    word.ai_verified_at = utcnow()
    word_repo.update(word)
    return WordVerificationResponse(
        word_id=word_id,
        state=verification_state(word.ai_provider, word.ai_verified_at),
        ai_verified_at=word.ai_verified_at,
    )


@router.delete("/{word_id}/verify", response_model=WordVerificationResponse)
def unverify_word(
    word_id: int, current_user: CurrentUser, word_repo: WordRepo, group_repo: GroupRepo
) -> WordVerificationResponse:
    """Withdraw verification. Reversible on purpose — someone who realises they
    approved a card too quickly needs a way to say so."""
    try:
        word = GetWordUseCase(word_repo, group_repo).execute(current_user.id, word_id)
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle_common_errors(exc)

    word.ai_verified_at = None
    word_repo.update(word)
    return WordVerificationResponse(
        word_id=word_id,
        state=verification_state(word.ai_provider, None),
        ai_verified_at=None,
    )


@router.patch("/bulk", response_model=BulkWordEditResponse)
def bulk_edit(
    payload: BulkWordEditRequest,
    current_user: CurrentUser,
    word_repo: WordRepo,
    group_repo: GroupRepo,
    revision_repo: WordRevisionRepo,
) -> BulkWordEditResponse:
    """Set the same fields on several cards at once.

    Words that are not this account's are skipped and reported rather than
    causing the whole request to fail: one bad id in a list of forty should not
    discard the other thirty-nine, and a bulk edit that quietly did less than
    asked is worse than one that says so.
    """
    updated = 0
    skipped: list[int] = []
    for word_id in payload.word_ids:
        try:
            word = GetWordUseCase(word_repo, group_repo).execute(current_user.id, word_id)
        except (EntityNotFoundError, PermissionDeniedError):
            skipped.append(word_id)
            continue

        changed = _apply_bulk_fields(word, payload, revision_repo)
        if changed:
            word_repo.update(word)
            updated += 1

    return BulkWordEditResponse(updated=updated, skipped=skipped)


def _apply_bulk_fields(word, payload: BulkWordEditRequest, revision_repo) -> bool:
    """Apply the set fields, recording each real change. Returns whether any."""
    changed = False
    for name in ("cefr_level", "part_of_speech", "category", "tags"):
        new_value = getattr(payload, name)
        # None means "leave alone", which is different from setting a field to
        # empty — a bulk form that omitted a field must not clear it.
        if new_value is None:
            continue
        old_value = getattr(word, name)
        if old_value == new_value:
            continue
        setattr(word, name, new_value)
        changed = True
        # Only the AI-authored fields carry history; category and tags are
        # organisational and were never model claims about the language.
        if name in {"cefr_level", "part_of_speech"}:
            revision_repo.record(
                word_id=word.id,
                field=name,
                before_value=old_value,
                after_value=new_value,
                source=EditSource.BULK.value,
            )
    return changed

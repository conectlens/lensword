"""Mapping helpers from domain entities / application DTOs to API response
schemas. Centralized here so word/group/room mapping logic isn't duplicated
across the groups, words, rooms, and review routers.
"""
from app.api.schemas.review import MnemonicResponse
from app.api.schemas.vocabulary import (
    GroupResponse,
    ReviewStateResponse,
    RoomPlacementResponse,
    RoomResponse,
    WordResponse,
)
from app.application.use_cases.vocabulary import GroupSummary, RoomSummary
from app.domain.entities import MnemonicNote, Room, Word


def word_to_response(word: Word) -> WordResponse:
    return WordResponse(
        id=word.id,
        group_id=word.group_id,
        term=word.term,
        target_language=word.target_language,
        translations=word.translations,
        example_sentence=word.example_sentence,
        mnemonic=word.mnemonic,
        category=word.category,
        synonyms=word.synonyms,
        antonyms=word.antonyms,
        topics=word.topics,
        review_state=ReviewStateResponse(
            strength=word.review_state.strength,
            ease_factor=word.review_state.ease_factor,
            interval_days=word.review_state.interval_days,
            repetitions=word.review_state.repetitions,
            due_at=word.review_state.due_at,
            last_reviewed_at=word.review_state.last_reviewed_at,
            status=word.review_state.status,
        ),
        created_at=word.created_at,
    )


def group_summary_to_response(summary: GroupSummary) -> GroupResponse:
    return GroupResponse(
        id=summary.group.id,
        name=summary.group.name,
        target_language=summary.group.target_language,
        created_at=summary.group.created_at,
        word_count=summary.word_count,
        mastered_count=summary.mastered_count,
        due_count=summary.due_count,
        last_reviewed_at=summary.last_reviewed_at,
    )


def room_to_response(room: Room, group_word_count: int) -> RoomResponse:
    return RoomResponse(
        id=room.id,
        group_id=room.group_id,
        name=room.name,
        icon=room.icon,
        created_at=room.created_at,
        placements=[
            RoomPlacementResponse(word_id=p.word_id, x_percent=p.x_percent, y_percent=p.y_percent, placed_at=p.placed_at)
            for p in room.placements
        ],
        group_word_count=group_word_count,
    )


def room_summary_to_response(summary: RoomSummary) -> RoomResponse:
    return room_to_response(summary.room, summary.group_word_count)


def mnemonic_to_response(note: MnemonicNote) -> MnemonicResponse:
    return MnemonicResponse(
        id=note.id,
        word_id=note.word_id,
        author_id=note.author_id,
        text=note.text,
        is_ai_generated=note.is_ai_generated,
        upvotes=note.upvotes,
        downvotes=note.downvotes,
        score=note.score,
        created_at=note.created_at,
    )

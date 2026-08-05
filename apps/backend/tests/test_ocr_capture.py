"""Screen-capture OCR into reviewable candidates (issue #84).

The issue asks for low-confidence text to be visibly flagged, denied
permission to produce a useful fallback, and no candidate to reach storage
before confirmation. Those are decided here and tested with a controlled
engine.

What is *not* here: golden-image tests against a real OCR engine, covering
subtitles, scans, low contrast and multilingual text. Those need the
`tesseract` binary, which is neither installed in this environment nor in CI,
and a golden-image test that runs against a stub proves nothing about OCR.
The Tesseract adapter is written and its result-mapping is tested against
recorded engine output; it has never been run against the real binary.
"""
from __future__ import annotations

import pytest

from app.domain.services.ocr import (
    LOW_CONFIDENCE,
    NOISE_FLOOR,
    BoundingBox,
    OcrResult,
    RecognisedWord,
    build_preview,
)
from app.infrastructure.ocr import NullOcrEngine, build_ocr_engine


def _word(text: str, confidence: float, x: int = 0) -> RecognisedWord:
    return RecognisedWord(
        text=text, confidence=confidence, box=BoundingBox(x=x, y=0, width=40, height=12)
    )


# --- Confidence: flagged, not dropped --------------------------------------


def test_low_confidence_text_is_flagged_for_review():
    result = OcrResult(words=[_word("gato", LOW_CONFIDENCE - 0.1)])

    preview = build_preview(result)

    assert preview.candidates[0].needs_review is True


def test_confident_text_is_not_flagged():
    preview = build_preview(OcrResult(words=[_word("gato", 0.98)]))

    assert preview.candidates[0].needs_review is False


def test_low_confidence_text_is_kept_rather_than_discarded():
    """Dropping uncertain-but-real words would silently lose the thing the user
    was trying to capture, and give no clue it happened. They are looking at
    the image and can correct in a second what the engine could not read."""
    preview = build_preview(OcrResult(words=[_word("gato", LOW_CONFIDENCE - 0.2)]))

    assert [c.text for c in preview.candidates] == ["gato"]


def test_noise_is_discarded_and_accounted_for():
    """Compression artefacts and page edges routinely score below the floor. A
    preview full of garbage is one nobody reads and everyone confirms blindly —
    but silently dropping them makes the count confusing."""
    result = OcrResult(words=[_word("gato", 0.9), _word("|~", NOISE_FLOOR - 0.1)])

    preview = build_preview(result)

    assert [c.text for c in preview.candidates] == ["gato"]
    assert "1 unreadable fragment(s) were discarded" in preview.warnings


def test_the_review_count_is_reported():
    result = OcrResult(words=[_word("gato", 0.99), _word("perro", 0.4), _word("casa", 0.5)])

    assert build_preview(result).needs_review_count == 2


def test_empty_text_is_not_a_candidate():
    assert build_preview(OcrResult(words=[_word("   ", 0.99)])).candidates == []


# --- Provenance ------------------------------------------------------------


def test_bounding_boxes_survive_into_the_preview():
    """Without them, correcting a misread word means reading the whole region
    again to work out which one it was."""
    result = OcrResult(words=[_word("gato", 0.5, x=120)])

    assert build_preview(result).candidates[0].box.x == 120


def test_the_detected_language_is_carried_as_a_hint():
    result = OcrResult(words=[_word("gato", 0.9)], detected_language="spa")

    assert build_preview(result).detected_language == "spa"


# --- Nothing is stored -----------------------------------------------------


def test_a_preview_produces_candidates_not_words():
    """A candidate is explicitly not a Word. Nothing here can be saved, which
    is the issue's requirement that no candidate reaches storage before
    confirmation, made structural."""
    preview = build_preview(OcrResult(words=[_word("gato", 0.99)]))

    candidate = preview.candidates[0]
    assert not hasattr(candidate, "id")
    assert not hasattr(candidate, "group_id")


# --- Degrading usefully ----------------------------------------------------


def test_an_empty_region_says_so_rather_than_failing():
    result = OcrResult(words=[], empty_reason="No OCR engine is configured")

    preview = build_preview(result)

    assert preview.candidates == []
    assert preview.warnings == ["No OCR engine is configured"]


def test_a_region_with_only_noise_reports_no_readable_text():
    preview = build_preview(OcrResult(words=[_word("~", 0.05)]))

    assert "No readable text was found" in preview.warnings[-1]


def test_the_null_engine_reports_a_reason_rather_than_raising():
    """So a capture with no engine reads as "OCR is not configured" instead of
    an error the user cannot act on."""
    result = NullOcrEngine().recognise(b"image")

    assert result.words == []
    assert result.empty_reason is not None


def test_a_missing_ocr_engine_degrades_to_null_rather_than_failing_startup():
    """OCR is one feature. An unreachable engine should disable screen capture,
    not stop the application booting."""
    engine = build_ocr_engine(enabled=True)

    assert isinstance(engine, NullOcrEngine)


def test_ocr_is_off_unless_asked_for():
    assert isinstance(build_ocr_engine(enabled=False), NullOcrEngine)


# --- Mapping the engine's own output ---------------------------------------
#
# Against recorded pytesseract output rather than a live binary. This pins the
# translation — confidence scale, layout rows, empty cells — which is where
# adapter bugs live; it does not test that Tesseract can read.


def test_engine_output_is_normalised_to_a_zero_to_one_scale():
    from app.infrastructure.ocr import _to_words

    words = _to_words(
        {"text": ["gato"], "conf": ["87.5"], "left": [10], "top": [20], "width": [30], "height": [12]}
    )

    assert words[0].confidence == 0.875


def test_layout_rows_are_not_mistaken_for_words():
    """pytesseract emits structural entries with a confidence of -1. Taken as
    words they would become empty candidates with impossible confidence."""
    from app.infrastructure.ocr import _to_words

    words = _to_words(
        {
            "text": ["", "gato"],
            "conf": ["-1", "90"],
            "left": [0, 10],
            "top": [0, 20],
            "width": [100, 30],
            "height": [50, 12],
        }
    )

    assert [w.text for w in words] == ["gato"]


def test_whitespace_only_cells_are_skipped():
    from app.infrastructure.ocr import _to_words

    words = _to_words(
        {"text": ["  "], "conf": ["95"], "left": [0], "top": [0], "width": [1], "height": [1]}
    )

    assert words == []


@pytest.mark.parametrize("confidence,expected", [(0.9, False), (LOW_CONFIDENCE - 0.01, True)])
def test_the_flag_threshold_is_applied_at_the_boundary(confidence, expected):
    assert _word("x", confidence).is_low_confidence is expected

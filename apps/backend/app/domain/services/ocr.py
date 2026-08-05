"""Turning a captured screen region into reviewable vocabulary (issue #84).

Two constraints from the issue shape everything here.

**A dedicated OCR engine, never a general LLM.** An LLM asked to read an image
will produce plausible text, and plausible is the failure mode that matters: a
model that silently "corrects" a misread word into a real one destroys the
evidence that it guessed. A real OCR engine reports per-word confidence, and
confidence is what makes review possible. So `OcrEngine` is a port, and what
it must return includes confidence and position — not just a string.

**Nothing reaches storage before a person confirms it.** The pipeline produces
*candidates*, and a candidate is explicitly not a word. Low-confidence text is
flagged rather than dropped, because the user is looking at the image and can
correct in a second what the engine could not read at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

# Below this, a word is shown but marked as probably misread. Chosen to be
# generous: a flagged word the user glances at and accepts costs a moment,
# whereas a dropped word costs them the thing they were trying to capture and
# gives no clue it happened.
LOW_CONFIDENCE = 0.75

# Below this the engine is not reading text so much as reporting noise —
# compression artefacts and page edges routinely score here. Kept out of the
# candidate list entirely, because a preview full of garbage is one nobody
# reads and everyone confirms blindly.
NOISE_FLOOR = 0.30


@dataclass(frozen=True)
class BoundingBox:
    """Where a word sat in the captured image, in pixels from the top left.

    Preserved so the preview can point at the word in the original rather than
    asking the user to find it. Without this, correcting a misread word means
    reading the whole region again to work out which one it was.
    """

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class RecognisedWord:
    text: str
    confidence: float
    box: BoundingBox

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < LOW_CONFIDENCE

    @property
    def is_noise(self) -> bool:
        return self.confidence < NOISE_FLOOR


@dataclass(frozen=True)
class OcrResult:
    words: list[RecognisedWord]
    # What the engine believed the language was, if it can say. Advisory: it is
    # a hint for the extraction pipeline, not an assertion, and a wrong guess
    # must not stop a capture being reviewed.
    detected_language: str | None = None
    # Set when the engine ran but produced nothing usable — a blank region, a
    # photograph, a solid colour. Distinguished from failure so the caller can
    # say "no text found" rather than "OCR failed".
    empty_reason: str | None = None

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


class OcrUnavailableError(Exception):
    """No OCR engine is configured or reachable."""


class ScreenCaptureDeniedError(Exception):
    """The operating system refused screen recording.

    Its own type because the remedy is specific and worth telling the user:
    macOS and Windows both require an explicit grant that only they can give,
    in a settings panel this application cannot open on their behalf.
    """


class OcrEngine(Protocol):
    """A real OCR engine. Structural, matching the other ports in this domain.

    Deliberately *not* satisfied by an AI provider. The AIProvider port exists
    and is tempting to reuse here, and reusing it would mean asking a language
    model to read pixels it cannot see and accepting whatever it invents.
    """

    def recognise(self, image: bytes) -> OcrResult: ...


@dataclass(frozen=True)
class OcrCandidate:
    """One reviewable term. Explicitly not a Word — nothing here is saved."""

    text: str
    confidence: float
    box: BoundingBox
    needs_review: bool


@dataclass
class CapturePreview:
    """What the user is shown before anything is stored."""

    candidates: list[OcrCandidate] = field(default_factory=list)
    detected_language: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_review_count(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.needs_review)


class CaptureMode(str, Enum):
    """How the region was obtained, which changes what to expect of it."""

    SCREEN_REGION = "screen_region"
    # A still from a video player: high contrast, few words, often burned-in
    # subtitles. Named because the confidence distribution differs enough that
    # a caller may want to treat it differently.
    SUBTITLE_FRAME = "subtitle_frame"


def build_preview(result: OcrResult) -> CapturePreview:
    """Turn an OCR result into something a person can correct.

    Noise is dropped and low confidence is flagged — not the other way round.
    Dropping uncertain-but-real words would silently lose the thing the user
    was trying to capture, and a preview full of artefacts is one nobody reads.
    """
    if result.empty_reason:
        return CapturePreview(warnings=[result.empty_reason])

    candidates = [
        OcrCandidate(
            text=word.text,
            confidence=word.confidence,
            box=word.box,
            needs_review=word.is_low_confidence,
        )
        for word in result.words
        if not word.is_noise and word.text.strip()
    ]

    warnings: list[str] = []
    dropped = sum(1 for word in result.words if word.is_noise)
    if dropped:
        # Reported rather than silent: "we read 4 words" when the region
        # clearly had 12 is confusing unless the other 8 are accounted for.
        warnings.append(f"{dropped} unreadable fragment(s) were discarded")
    if not candidates:
        warnings.append("No readable text was found in the captured region")

    return CapturePreview(
        candidates=candidates,
        detected_language=result.detected_language,
        warnings=warnings,
    )

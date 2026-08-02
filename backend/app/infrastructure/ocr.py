"""Concrete OCR adapters (issue #84).

Tesseract is the engine, reached through `pytesseract`. It is a real OCR
engine rather than a language model — the distinction the issue insists on —
and it reports per-word confidence, which is what makes the review step in
`build_preview` possible at all.

Both imports are deferred. Neither the Python package nor the `tesseract`
binary is a hard dependency: an installation with no OCR configured should
start and run normally, with screen capture reporting that it is unavailable
rather than the application failing to boot.

`NullOcrEngine` is the honest default. It does not pretend to read anything.
"""
from __future__ import annotations

import logging
import os
import tempfile

from app.domain.services.ocr import (
    BoundingBox,
    OcrResult,
    OcrUnavailableError,
    RecognisedWord,
)

logger = logging.getLogger(__name__)

# pytesseract reports confidence as 0-100, or -1 for entries that are layout
# boxes rather than words.
_NOT_A_WORD = -1


class NullOcrEngine:
    """The default when nothing is configured.

    Returns an empty result with a reason rather than raising, so a capture
    with no engine reads as "no text found, OCR is not configured" instead of
    an error the user cannot act on.
    """

    def recognise(self, image: bytes) -> OcrResult:
        del image
        return OcrResult(words=[], empty_reason="No OCR engine is configured")


class TesseractOcrEngine:
    """Tesseract, via pytesseract.

    The binary is checked at construction rather than at first use, so a
    misconfigured deployment fails while someone is looking at the console
    instead of the first time a user tries to capture something.
    """

    def __init__(self, languages: str = "eng"):
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover - depends on install
            raise OcrUnavailableError(
                "pytesseract is not installed; screen capture OCR is unavailable"
            ) from exc
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:  # noqa: BLE001 - pytesseract raises several types
            raise OcrUnavailableError(
                "the tesseract binary was not found; install it or leave OCR disabled"
            ) from exc
        self.languages = languages

    def recognise(self, image: bytes) -> OcrResult:
        import pytesseract
        from PIL import Image

        # Written to a temporary file and removed in a finally block. The issue
        # requires captured images not to outlive processing, and a capture is
        # someone's screen — whatever happened to be on it, not only the words
        # they meant to grab.
        handle, path = tempfile.mkstemp(suffix=".png")
        try:
            with os.fdopen(handle, "wb") as spilled:
                spilled.write(image)
            with Image.open(path) as opened:
                data = pytesseract.image_to_data(
                    opened, lang=self.languages, output_type=pytesseract.Output.DICT
                )
        finally:
            os.unlink(path)

        return OcrResult(words=_to_words(data), detected_language=self.languages)


def _to_words(data: dict) -> list[RecognisedWord]:
    words: list[RecognisedWord] = []
    for index, text in enumerate(data.get("text", [])):
        raw_confidence = float(data["conf"][index])
        if raw_confidence == _NOT_A_WORD or not str(text).strip():
            continue
        words.append(
            RecognisedWord(
                text=str(text).strip(),
                # Normalised to 0-1 here rather than at every call site, so the
                # thresholds in the domain are expressed in one scale.
                confidence=raw_confidence / 100.0,
                box=BoundingBox(
                    x=int(data["left"][index]),
                    y=int(data["top"][index]),
                    width=int(data["width"][index]),
                    height=int(data["height"][index]),
                ),
            )
        )
    return words


def build_ocr_engine(enabled: bool, languages: str = "eng"):
    """The configured engine, or the null one.

    Failure to build Tesseract degrades to null rather than propagating: OCR
    is one feature, and an unreachable engine should disable screen capture
    rather than stop the application starting.
    """
    if not enabled:
        return NullOcrEngine()
    try:
        return TesseractOcrEngine(languages)
    except OcrUnavailableError as exc:
        logger.warning("OCR requested but unavailable: %s", exc)
        return NullOcrEngine()

"""The shape a parsed document takes, and the limits every parser works within.

Issue #85. A document becomes sections, sections become sentences, and a
sentence is what a vocabulary candidate points back at. That chain is the
point: a card extracted from page 40 of a book should still be able to say
which sentence it came from a year later, and "provenance" without that is
just a filename.

Nothing here parses anything. Parsers live in infrastructure (they need
pypdf, python-docx and friends); this is the vocabulary they all produce and
the bounds they all respect, so a new format cannot quietly invent either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class DocumentTooLargeError(Exception):
    """Refused before parsing, on declared size."""


class DocumentStructureError(Exception):
    """Refused during parsing: encrypted, corrupt, or beyond a structural bound."""


# Bounds. These are refusals, not truncations: silently importing the first
# 200 pages of a 900-page book would look like success and lose most of the
# document, which is worse than an error saying it was too big.
MAX_BYTES = 20 * 1024 * 1024
MAX_SECTIONS = 2_000
MAX_SENTENCES = 50_000
# Guards the archive formats. EPUB and DOCX are zip containers, so a small
# upload can declare an enormous decompressed size — the classic zip bomb. The
# ratio is checked against what was actually read, not what the archive claims.
MAX_DECOMPRESSION_RATIO = 200


@dataclass(frozen=True)
class Sentence:
    text: str
    # Position within its section, so a candidate can be located precisely
    # rather than only attributed to a page.
    index: int


@dataclass(frozen=True)
class Section:
    """A page, chapter, subtitle cue, or heading-delimited run of prose.

    One type for all of them deliberately. A caller that wanted to know
    "page 12" versus "chapter 3" would be asking the wrong question — what it
    needs is a stable label to show a user, and `label` is that.
    """

    label: str
    sentences: list[Sentence]


@dataclass
class ParsedDocument:
    source_name: str
    media_type: str
    sections: list[Section] = field(default_factory=list)
    # Set when a parser had to degrade rather than fail — a PDF page that is a
    # scanned image and yields no text, for example. Surfaced so a preview can
    # say "3 pages produced no text" instead of quietly importing less.
    warnings: list[str] = field(default_factory=list)

    @property
    def sentence_count(self) -> int:
        return sum(len(section.sentences) for section in self.sections)

    def locate(self, section_label: str, sentence_index: int) -> str | None:
        """The sentence a candidate came from, or None if it no longer exists."""
        for section in self.sections:
            if section.label != section_label:
                continue
            for sentence in section.sentences:
                if sentence.index == sentence_index:
                    return sentence.text
        return None


# Sentence-ending punctuation followed by whitespace and something that starts
# a new sentence. Deliberately simple: a full NLP segmenter is a dependency and
# a language question, and getting this slightly wrong costs a slightly odd
# excerpt rather than a wrong card — the term is what matters, the sentence is
# context.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])[\s\n]+(?=[^\s])")
_WHITESPACE = re.compile(r"\s+")


def split_sentences(text: str) -> list[Sentence]:
    """Normalise whitespace and split into sentences.

    Whitespace is collapsed first because every format arrives with different
    line breaking — PDFs break mid-sentence at the page width, subtitles break
    on display timing — and a sentence that keeps those breaks is unreadable
    as an excerpt.
    """
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if not collapsed:
        return []
    parts = [part.strip() for part in _SENTENCE_BREAK.split(collapsed)]
    return [Sentence(text=part, index=index) for index, part in enumerate(p for p in parts if p)]


def build_document(
    source_name: str,
    media_type: str,
    raw_sections: list[tuple[str, str]],
    warnings: list[str] | None = None,
) -> ParsedDocument:
    """Assemble a document from (label, text) pairs, enforcing structural bounds.

    Sections with no sentences are dropped rather than kept empty: a 400-page
    PDF of scans would otherwise produce 400 sections a user has to scroll
    past to discover there is nothing in any of them. The count of dropped
    sections becomes a warning instead.
    """
    if len(raw_sections) > MAX_SECTIONS:
        raise DocumentStructureError(
            f"document has {len(raw_sections)} sections, more than the {MAX_SECTIONS} supported"
        )

    collected: list[Section] = []
    empty = 0
    total = 0
    for label, text in raw_sections:
        sentences = split_sentences(text)
        if not sentences:
            empty += 1
            continue
        total += len(sentences)
        if total > MAX_SENTENCES:
            raise DocumentStructureError(
                f"document has more than the {MAX_SENTENCES} sentences supported"
            )
        collected.append(Section(label=label, sentences=sentences))

    all_warnings = list(warnings or [])
    if empty:
        all_warnings.append(f"{empty} section(s) contained no readable text and were skipped")
    return ParsedDocument(
        source_name=source_name,
        media_type=media_type,
        sections=collected,
        warnings=all_warnings,
    )

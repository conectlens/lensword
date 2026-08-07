"""Preview-only, bounded developer-context vocabulary extraction (#188).

This module deliberately stops at a local preview.  A caller must obtain an
explicit confirmation before sending candidates to LensWord persistence.

Ranking (issue #188 TODO 2) combines three deterministic signals, in this
priority order, so a caller never has to guess which candidates matter most:

1. ``occurrences`` — how often the term recurred in the bounded input.
2. ``technical_relevance`` — a bounded, offline heuristic ("does this look
   like an identifier: CamelCase, snake_case, dotted/hyphenated, or carries
   a digit" rather than an AI judgement call — this module stays
   deterministic per the architecture-boundary convention every other #188
   surface follows).
3. ``novelty`` — whether the term is *not* already in the learner's known
   vocabulary. This module never calls the backend to find that out (it
   stays offline, matching the CLI's own "never contacts the backend"
   guarantee); a caller who has bounded access to the learner's word list
   (e.g. via the ``lensword.check_known_term``/``lensword.get_language_profile``
   MCP tools) may pass it in as ``known_terms``. Left unset, every candidate
   is neutral on this axis and ranking falls back to signals 1 and 2 only.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import AbstractSet


class ContextImportRejected(ValueError):
    """Raised when context exceeds safe import limits."""


@dataclass(frozen=True)
class ContextImportPolicy:
    max_characters: int = 50_000
    max_candidates: int = 50
    max_term_length: int = 64

    def __post_init__(self) -> None:
        if self.max_characters < 1 or self.max_candidates < 1 or self.max_term_length < 2:
            raise ValueError("context import limits must be positive")


@dataclass(frozen=True)
class ContextCandidate:
    term: str
    occurrences: int
    source_kind: str
    source_ref: str
    # Issue #188 TODO 2's second ranking signal: a bounded, deterministic
    # heuristic, never an AI call. True when at least one raw occurrence of
    # this term looked identifier-like (CamelCase/snake_case/dotted/
    # hyphenated/carrying a digit) rather than plain prose.
    technical_relevance: bool = False
    # The third ranking signal. `None` means "unknown" (no `known_terms` was
    # supplied to `preview_context`) rather than "not novel" — a caller must
    # not be able to tell "definitely already known" apart from "we didn't
    # check" by reading this field alone.
    novel: bool | None = None


@dataclass(frozen=True)
class ContextImportPreview:
    candidates: tuple[ContextCandidate, ...]
    source_kind: str
    source_ref: str
    truncated: bool
    requires_confirmation: bool = True
    writes_performed: bool = False


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|private[_ -]?key)\s*[:=]\s*[^\s,;]+"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.S)
_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")
_TOKEN = re.compile(r"[\w][\w+#./-]{1,63}", re.UNICODE)
_IGNORED = frozenset(
    "a an and are as at be by for from if in is it of on or the this to with you your".split()
)


def _redact_secrets(text: str) -> str:
    redacted = _PRIVATE_KEY.sub(" ", text)
    redacted = _SECRET_ASSIGNMENT.sub(" ", redacted)
    return _JWT.sub(" ", redacted)


# Technical-relevance heuristic (issue #188 TODO 2): bounded pattern checks
# on the *raw* (pre-casefold) token, since casefolding destroys exactly the
# signal CamelCase/snake_case detection needs. Deliberately simple regexes,
# not a dictionary or model call — the goal is "looks like an identifier",
# not "is a real technical term".
_INNER_UPPERCASE = re.compile(r"[a-z][A-Z]")  # camelCase / PascalCase transition
_SNAKE_CASE = re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]")
_HAS_DIGIT = re.compile(r"\d")
_HAS_TECHNICAL_SEPARATOR = re.compile(r"[./#+-]")


def _looks_technical(raw_term: str) -> bool:
    return bool(
        _INNER_UPPERCASE.search(raw_term)
        or _SNAKE_CASE.search(raw_term)
        or _HAS_DIGIT.search(raw_term)
        or _HAS_TECHNICAL_SEPARATOR.search(raw_term)
    )


def preview_context(
    text: str,
    *,
    source_kind: str,
    source_ref: str,
    policy: ContextImportPolicy | None = None,
    known_terms: AbstractSet[str] | None = None,
) -> ContextImportPreview:
    """Extract recurring technical candidates without persisting anything.

    `known_terms` is an optional, caller-supplied set of casefolded terms
    the learner already knows (issue #188 TODO 2's novelty signal). This
    function never fetches it itself — see the module docstring.
    """
    policy = policy or ContextImportPolicy()
    if not source_kind.strip() or not source_ref.strip() or len(source_ref) > 256:
        raise ContextImportRejected("source kind and bounded source reference are required")
    if not isinstance(text, str) or not text.strip():
        raise ContextImportRejected("context must contain text")
    truncated = len(text) > policy.max_characters
    bounded_text = text[: policy.max_characters]
    counts: Counter[str] = Counter()
    technical: dict[str, bool] = {}
    for raw in _TOKEN.findall(_redact_secrets(bounded_text)):
        term = raw.strip("._-/")
        normalized = term.casefold()
        if len(term) < 2 or len(term) > policy.max_term_length or normalized in _IGNORED:
            continue
        if normalized.startswith(("http", "www")):
            continue
        counts[normalized] += 1
        # An occurrence only ever turns a term's technical flag on, never
        # back off — "grep FastAPI docs" should still flag "FastAPI" even
        # if it also appears lowercase elsewhere in the same input.
        technical[normalized] = technical.get(normalized, False) or _looks_technical(term)

    def _novelty(normalized: str) -> bool | None:
        if known_terms is None:
            return None
        return normalized not in known_terms

    # Primary key: occurrences (recurrence). Ties are broken by the two
    # additional signals TODO 2 asks for — technical-relevance, then
    # novelty — before finally falling back to alphabetical order so the
    # result stays fully deterministic.
    def _sort_key(item: tuple[str, int]) -> tuple:
        normalized, occurrences = item
        novelty = _novelty(normalized)
        return (
            -occurrences,
            0 if technical.get(normalized) else 1,
            0 if novelty else 1,
            normalized,
        )

    ranked = sorted(counts.items(), key=_sort_key)
    candidates = tuple(
        ContextCandidate(
            term=term,
            occurrences=occurrences,
            source_kind=source_kind,
            source_ref=source_ref,
            technical_relevance=technical.get(term, False),
            novel=_novelty(term),
        )
        for term, occurrences in ranked[: policy.max_candidates]
    )
    return ContextImportPreview(
        candidates=candidates,
        source_kind=source_kind,
        source_ref=source_ref,
        truncated=truncated,
    )

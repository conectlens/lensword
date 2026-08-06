"""Preview-only, bounded developer-context vocabulary extraction (#188).

This module deliberately stops at a local preview.  A caller must obtain an
explicit confirmation before sending candidates to LensWord persistence.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


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


def preview_context(
    text: str,
    *,
    source_kind: str,
    source_ref: str,
    policy: ContextImportPolicy | None = None,
) -> ContextImportPreview:
    """Extract recurring technical candidates without persisting anything."""
    policy = policy or ContextImportPolicy()
    if not source_kind.strip() or not source_ref.strip() or len(source_ref) > 256:
        raise ContextImportRejected("source kind and bounded source reference are required")
    if not isinstance(text, str) or not text.strip():
        raise ContextImportRejected("context must contain text")
    truncated = len(text) > policy.max_characters
    bounded_text = text[: policy.max_characters]
    counts: Counter[str] = Counter()
    for raw in _TOKEN.findall(_redact_secrets(bounded_text)):
        term = raw.strip("._-/")
        normalized = term.casefold()
        if len(term) < 2 or len(term) > policy.max_term_length or normalized in _IGNORED:
            continue
        if normalized.startswith(("http", "www")):
            continue
        counts[normalized] += 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    candidates = tuple(
        ContextCandidate(term=term, occurrences=occurrences, source_kind=source_kind, source_ref=source_ref)
        for term, occurrences in ranked[: policy.max_candidates]
    )
    return ContextImportPreview(
        candidates=candidates,
        source_kind=source_kind,
        source_ref=source_ref,
        truncated=truncated,
    )

"""Pure, deterministic building blocks for running companion tasks (#197).

`companion_tasks.py` owns the task *state machine*; this module owns the two
`CompanionTaskType`s bounded enough to run as background jobs today
(`EXTRACTION`, `PLAN_GENERATION`). Everything here is deterministic and I/O
free so it is testable without a database, a scheduler, or an AI provider —
the infrastructure job in `app.infrastructure.jobs.companion_task_dispatch`
is the only place that touches either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Same shape as ExtractVocabularyUseCase._fallback's deterministic tokenizer
# (app/application/use_cases/extract.py): words of 3+ letters, casefold-
# deduplicated, first-seen order preserved. Reusing the pattern rather than
# importing that private method keeps this module dependency-free, but the
# candidates it produces are exactly the same shape extraction already
# promises callers when no AI provider is configured.
_TOKEN = re.compile(r"[^\W\d_][\w'-]*", flags=re.UNICODE)


def extract_candidate_terms(text: str, max_terms: int) -> list[str]:
    """Split `text` into a bounded, ordered, deduplicated candidate list.

    This is the whole of what the EXTRACTION task type processes "one unit"
    of: one candidate term. AI-provider enrichment (translations, examples)
    is deliberately not part of the background executor in this pass — see
    the module docstring in companion_task_dispatch.py for why.
    """
    if max_terms < 1:
        raise ValueError("max_terms must be positive")
    candidates: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(text):
        normalized = token.casefold()
        if len(normalized) < 3 or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(token)
        if len(candidates) == max_terms:
            break
    return candidates


@dataclass(frozen=True)
class DueWordRef:
    """The minimal, already-authorized fact a plan-generation unit needs.

    Carrying the term alongside the id means the background job never has to
    re-open a WordRepository mid-run to render an activity prompt — the
    caller that created the task already read it under the requesting
    user's authorization, and the task's `input` field is the only channel
    the executor reads from.
    """

    word_id: int
    term: str

    def __post_init__(self) -> None:
        if self.word_id < 1:
            raise ValueError("word_id must be positive")
        if not self.term.strip() or len(self.term) > 255:
            raise ValueError("term must contain 1-255 characters")


def plan_micro_session_units(due_words: list[DueWordRef], size: int) -> list[DueWordRef]:
    """Bound a due-word list to the number of activities a plan will create.

    One unit of PLAN_GENERATION work is "create one bounded recall activity
    for one due word" — this just decides which due words are in scope,
    deterministically (already-due order, first `size` of them).
    """
    if size < 1:
        raise ValueError("size must be positive")
    return list(due_words[:size])

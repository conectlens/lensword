"""Pure, deterministic building blocks for running companion tasks (#197).

`companion_tasks.py` owns the task *state machine*; this module owns the
one `CompanionTaskType` bounded enough to run as a background job today
(`EXTRACTION`). `PLAN_GENERATION` deliberately has no counterpart here: it
already has a real, synchronous, context-aware lifecycle of its own via
`app.application.use_cases.companion_planning` (#194 TODO 4), discovered
while rebasing this change onto `development` — see
`app.infrastructure.jobs.companion_task_dispatch`'s module docstring for the
full reasoning. Everything here is deterministic and I/O free so it is
testable without a database, a scheduler, or an AI provider — the
infrastructure job in `app.infrastructure.jobs.companion_task_dispatch` is
the only place that touches either.
"""
from __future__ import annotations

import re

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

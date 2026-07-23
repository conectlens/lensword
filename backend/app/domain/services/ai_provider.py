"""AIProvider port (hexagonal-architecture sense).

Decoupled from any specific backend (Ollama, a cloud LLM, etc.) — concrete
providers live in infrastructure/ and are wired up in Phase 1. Zero
third-party/framework imports here, preserving the domain layer's boundary
(see app.domain.repositories module docstring for the same rule applied to
data-access ports).
"""
from __future__ import annotations

from typing import Protocol


class AIProvider(Protocol):
    """Awaitable by design.

    Generation takes seconds, so a synchronous port would force every caller
    to hold an OS thread for the duration; under load that exhausts the
    server's bounded threadpool and stalls unrelated requests. `async def` in
    a Protocol is plain language syntax and imports nothing, so the domain
    layer stays framework-free.
    """

    async def suggest_mnemonic(self, word: str, context: str) -> str: ...

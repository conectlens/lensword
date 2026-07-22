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
    def suggest_mnemonic(self, word: str, context: str) -> str: ...

"""Backwards-compatible import surface for the AI provider adapters.

The concrete adapters and the request-building/Template Method plumbing they
share used to live directly in this module. Issue #315 (Gemini, Vertex AI,
and OpenAI adapters, alongside a refactor of OllamaProvider onto a shared
base) split them into `app.infrastructure.ai_providers/` — `base.py` for the
shared Template Method and request builders, `ollama.py`/`google.py`/
`openai_provider.py` for the concrete adapters, `factory.py` for
`build_ai_provider`.

This module re-exports the same names every existing caller already imports
from `app.infrastructure.ai` (`app/api/deps.py`'s `build_ai_provider`, and
every test file's `OllamaProvider`/`DATA_BLOCK_BEGIN`/etc.) so nothing
outside this package needs to change its import path.
"""
from __future__ import annotations

from app.infrastructure.ai_providers.base import (
    AI_SYSTEM_INSTRUCTION,
    DATA_BLOCK_BEGIN,
    DATA_BLOCK_END,
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TERM_MAX_CHARS,
    _as_data,
    _unavailable_error,
    build_converse_request,
    build_extraction_request,
    build_learning_path_request,
    build_scenario_evaluation_request,
    build_suggestion_request,
)
from app.infrastructure.ai_providers.factory import SUPPORTED_AI_PROVIDERS, build_ai_provider
from app.infrastructure.ai_providers.ollama import OllamaProvider

# TODO(#315, in progress): GeminiProvider/VertexAIProvider (google.py) and
# OpenAIProvider (openai_provider.py) are re-exported here too once those
# modules exist — this narrower list is a deliberate, temporary checkpoint so
# OllamaProvider's refactor onto the shared base can be verified and
# committed on its own before the new providers are built on top of it.
# factory.py's SUPPORTED_AI_PROVIDERS/build_ai_provider stay ollama-only
# until then too.

__all__ = [
    "AI_SYSTEM_INSTRUCTION",
    "DATA_BLOCK_BEGIN",
    "DATA_BLOCK_END",
    "DEFAULT_CONTEXT_MAX_CHARS",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_TERM_MAX_CHARS",
    "OllamaProvider",
    "SUPPORTED_AI_PROVIDERS",
    "_as_data",
    "_unavailable_error",
    "build_ai_provider",
    "build_converse_request",
    "build_extraction_request",
    "build_learning_path_request",
    "build_scenario_evaluation_request",
    "build_suggestion_request",
]

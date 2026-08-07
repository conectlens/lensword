---
title: "ADR 0003: AI provider foundation audit"
description: Architecture decision record.
---

# ADR 0003: AI provider foundation audit

**Status:** Accepted for Phase 0

## Context

Issue #74 establishes the minimum AI foundation before vocabulary acquisition
features are added. This audit records the actual `development` surface so a
later phase does not mistake a planned adapter or prompt for a shipped one.

## Findings

- `AIProvider` currently exposes only `suggest_mnemonic(word, context)`.
- `OllamaProvider` is the sole concrete adapter. It implements the mnemonic
  operation, bounded output, timeouts, and prompt/data separation.
- No OpenAI, DeepSeek, or Vertex adapter exists. No configuration value may
  claim to enable one.
- There is no provider orchestrator, enrichment operation, or vocabulary
  extraction operation yet.
- The mnemonic prompt protects supplied vocabulary data with delimiters, but
  there are no enrichment or extraction prompts to evaluate for a target
  language requirement.

## Decision

Phase 0 adds only the provider operations needed to implement an honest,
AI-backed extraction path and its explicit test/demo fallback. It must not
advertise unimplemented providers or silently substitute a local heuristic
when AI is disabled.

Each future provider adapter must implement every operation added to the port
or be excluded by configuration. DeepSeek and Vertex remain documented gaps;
they are not stubs because an importable but non-functional provider would
make the configured-provider contract misleading.

Every enrichment and extraction prompt introduced after this audit must state
that examples are written in the requested target language, while retaining
the same untrusted-data boundary used by the mnemonic prompt.

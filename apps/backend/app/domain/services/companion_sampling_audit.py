"""Sampling provenance/audit records (issue #195, TODO 4).

A queryable record of *how* one piece of sampled companion content came to
exist — which host/model produced it (when known), which prompt template
version, a reference to the source facts (a hash, never the raw text), the
validation outcome, and which of the three paths in TODO 0 was actually
taken. This module intentionally never carries a raw prompt or raw learner
facts; the hash-chaining and redaction themselves are `mcp_policy.py`'s
`redact_and_chain`, reused rather than reimplemented, in the router that
persists these.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SamplingFallbackPath(StrEnum):
    SAMPLING_SUCCEEDED = "sampling_succeeded"
    SAMPLING_FAILED_FELL_BACK_TO_LOCAL_AI = "sampling_failed_fell_back_to_local_ai"
    SAMPLING_UNAVAILABLE_USED_DETERMINISTIC = "sampling_unavailable_used_deterministic"


@dataclass(frozen=True)
class CompanionSamplingEvent:
    id: int | None
    session_id: str
    user_id: int
    requester: str
    host_client_id: str | None
    model: str | None
    prompt_template_version: str
    source_facts_ref: str
    validation_result: str
    fallback_path: SamplingFallbackPath
    previous_hash: str
    event_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.session_id or len(self.session_id) > 64:
            raise ValueError("sampling event session id must contain 1-64 characters")
        if not self.requester.strip() or len(self.requester) > 255:
            raise ValueError("sampling event requester must contain 1-255 characters")
        if self.host_client_id is not None and len(self.host_client_id) > 128:
            raise ValueError("sampling event host_client_id is limited to 128 characters")
        if self.model is not None and len(self.model) > 128:
            raise ValueError("sampling event model is limited to 128 characters")
        if not self.prompt_template_version.strip() or len(self.prompt_template_version) > 32:
            raise ValueError("sampling event prompt_template_version must contain 1-32 characters")
        # A reference (e.g. a sha256 hex digest), never raw facts text.
        if not self.source_facts_ref.strip() or len(self.source_facts_ref) > 128:
            raise ValueError("sampling event source_facts_ref must contain 1-128 characters")
        if not self.validation_result.strip() or len(self.validation_result) > 255:
            raise ValueError("sampling event validation_result must contain 1-255 characters")

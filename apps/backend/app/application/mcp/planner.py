"""Bounded natural-language command planning for LensWord MCP clients.

This is not an agent loop: it recognises a deliberately small command grammar
and emits typed steps from the contract registry. Unknown or ambiguous text is
returned as an unexecutable preview rather than guessed into a tool call.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from json import dumps
import re
from typing import Iterable

from app.application.mcp.contracts import TOOL_CONTRACTS
from app.domain.entities import Group
from app.domain.services.mcp_policy import AccessClass


class PlanError(ValueError): pass
class PlanConfirmationRequired(PlanError): pass
class PlanCancelled(PlanError): pass


@dataclass(frozen=True, slots=True)
class PlanStep:
    id: str
    tool: str
    payload: dict
    access: AccessClass
    estimated_effect: str

    @property
    def requires_confirmation(self) -> bool:
        return self.access != AccessClass.READ


@dataclass(frozen=True, slots=True)
class LearningPlan:
    id: str
    command: str
    assumptions: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    executable: bool
    reason: str | None = None

    @property
    def requires_confirmation(self) -> bool:
        return any(step.requires_confirmation for step in self.steps)

    def preview(self) -> dict:
        return {"id": self.id, "command": self.command, "assumptions": list(self.assumptions), "steps": [{**asdict(step), "access": step.access.value, "requires_confirmation": step.requires_confirmation} for step in self.steps], "requires_confirmation": self.requires_confirmation, "executable": self.executable, "reason": self.reason}


class CommandPlanner:
    """Resolve a small, reviewable command grammar into current capabilities."""
    def __init__(self, capabilities: Iterable[str] | None = None):
        self.capabilities = frozenset((contract.name for contract in TOOL_CONTRACTS) if capabilities is None else capabilities)
        self.contracts = {contract.name: contract for contract in TOOL_CONTRACTS}

    def plan(self, command: str, groups: Iterable[Group], *, source_text: str | None = None) -> LearningPlan:
        normalized = " ".join(command.strip().split())
        if not normalized:
            return self._rejected(command, "A command is required.")
        group, group_assumption = self._resolve_group(normalized, groups)
        if group_assumption.startswith("Ambiguous"):
            return self._rejected(normalized, group_assumption)
        lower = normalized.lower()
        if "prepare" in lower and "session" in lower:
            duration = self._duration(lower)
            if duration is None:
                return self._rejected(normalized, "Specify a session duration, for example '15-minute'.")
            payload = {"limit": min(100, max(1, duration * 2)), "request_id": self._request_id(normalized, "session")}
            if group is not None: payload["group_id"] = group.id
            assumptions = [f"Two review items per minute is used to estimate a {duration}-minute session."]
            if group_assumption: assumptions.append(group_assumption)
            return self._accepted(normalized, assumptions, PlanStep("prepare-session", "lensword_create_study_session", payload, AccessClass.WRITE, f"Create a session of up to {payload['limit']} review items."))
        if "extract" in lower and ("word" in lower or "vocabulary" in lower):
            if group is None:
                return self._rejected(normalized, "Name exactly one target group before extracting vocabulary.")
            if not source_text:
                return self._rejected(normalized, "Provide the document text through the approved content-source adapter.")
            if len(source_text) > 20_000:
                return self._rejected(normalized, "Document text exceeds the current 20,000-character capability limit.")
            level = re.search(r"\b([abc][12])\+?\b", lower)
            assumptions = [f"Extract into '{group.name}'.", "The source text is treated as data, not instructions."]
            if level: assumptions.append(f"CEFR threshold {level.group(1).upper()} is a client-side selection hint; the registered extractor has no CEFR filter.")
            payload = {"group_id": group.id, "text": source_text, "target_language": group.target_language.value, "max_items": 50, "request_id": self._request_id(normalized, "extract")}
            return self._accepted(normalized, assumptions, PlanStep("extract-vocabulary", "lensword_extract_vocabulary", payload, AccessClass.WRITE, "Create up to 50 extracted vocabulary candidates."))
        return self._rejected(normalized, "The command is outside the bounded learning-command grammar.")

    def _accepted(self, command: str, assumptions: list[str], step: PlanStep) -> LearningPlan:
        if step.tool not in self.capabilities or step.tool not in self.contracts:
            return self._rejected(command, f"Required capability {step.tool} is unavailable.")
        return LearningPlan(self._request_id(command, f"{step.id}:{dumps(step.payload, sort_keys=True)}"), command, tuple(assumptions), (step,), True)

    def _rejected(self, command: str, reason: str) -> LearningPlan:
        return LearningPlan(self._request_id(command, "rejected"), command, (), (), False, reason)

    @staticmethod
    def _request_id(command: str, suffix: str) -> str:
        return "plan-" + sha256(f"{command}:{suffix}".encode()).hexdigest()[:24]

    @staticmethod
    def _duration(command: str) -> int | None:
        match = re.search(r"\b(\d{1,3})\s*(?:-| )?min(?:ute)?s?\b", command)
        return int(match.group(1)) if match and 1 <= int(match.group(1)) <= 60 else None

    @staticmethod
    def _resolve_group(command: str, groups: Iterable[Group]) -> tuple[Group | None, str]:
        available = list(groups)
        ids = re.findall(r"(?:group|deck)\s*#?(\d+)\b", command.lower())
        if ids:
            matches = [group for group in available if group.id == int(ids[-1])]
            return (matches[0], "") if matches else (None, "The requested group was not found.")
        matches = [group for group in available if group.name.lower() in command.lower()]
        if len(matches) == 1: return matches[0], ""
        if len(matches) > 1: return None, "Ambiguous group reference; name one group exactly."
        return (available[0], f"No group was named; '{available[0].name}' was selected.") if len(available) == 1 else (None, "")

"""Common interfaces shared by all evolution backends."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvolveCandidate:
    """One unit of evolution work, drained from the queue."""
    queue_id: str
    kind: str                    # 'fix' | 'derived' | 'captured'
    skill_id: str | None         # None for 'captured'
    metrics: dict[str, Any] = field(default_factory=dict)
    trigger_task_id: str | None = None
    workdir: str = ""            # for backends that want context (codex --cd, etc.)


@dataclass
class EvolveResult:
    """What a backend returns after attempting one candidate."""
    success: bool
    content: str = ""            # raw LLM output (may contain SKILL.md body)
    new_skill_path: str | None = None
    error: str | None = None
    cost_usd: float = 0.0
    backend_name: str = ""
    deferred: bool = False       # True for the task backend (waiting for /sf evolve)
    deferred_reason: str = ""

    @classmethod
    def deferred_result(cls, reason: str, backend_name: str = "task") -> "EvolveResult":
        return cls(success=True, deferred=True, deferred_reason=reason,
                   backend_name=backend_name)

    @classmethod
    def failure(cls, error: str, backend_name: str = "") -> "EvolveResult":
        return cls(success=False, error=error, backend_name=backend_name)


class EvolverBackend(abc.ABC):
    """All backends implement this minimal interface.

    Keep the surface small — callers only need `available()` + `run()`.
    """

    name: str = ""

    @abc.abstractmethod
    def available(self) -> bool:
        """Runtime probe — is the CLI installed, is auth valid, etc."""

    @abc.abstractmethod
    async def run(self, candidate: EvolveCandidate, prompt: str) -> EvolveResult:
        """Execute one evolution. `prompt` is the rendered analyzer prompt."""

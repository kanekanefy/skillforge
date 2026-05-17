"""Evolution backends — strategy pattern over how to run the LLM step.

Backends:
    codex       — `codex exec --json`, uses ChatGPT subscription (zero cost)
    claude-p    — `claude -p --output-format json`, needs ANTHROPIC_API_KEY
                  (gets free in June 2026 via subscription credit pool)
    task        — defer to next session; user runs /sf evolve manually
                  (only path that doesn't require external CLI auth)

The Stop hook spawns a worker that picks one of these based on user
config + availability detection.
"""

from .base import EvolverBackend, EvolveCandidate, EvolveResult
from .codex import CodexBackend
from .claude_p import ClaudePBackend
from .task import TaskBackend
from .detect import select_backend, available_backends

__all__ = [
    "EvolverBackend", "EvolveCandidate", "EvolveResult",
    "CodexBackend", "ClaudePBackend", "TaskBackend",
    "select_backend", "available_backends",
]

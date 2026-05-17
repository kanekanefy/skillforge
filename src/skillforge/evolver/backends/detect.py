"""Backend selection — driven by user config + runtime availability.

Resolution order:
  1. If user pinned `evolver.backend` to a specific name, honor that
     (but emit a warning if it's not available; fall through to auto).
  2. If `evolver.backend = auto` (default), pick first available from:
        codex > claude-p > task
     This makes the install path "install codex CLI + login = real-time
     evolution for free" without any further config.
"""

from __future__ import annotations

from ... import userconfig
from .base import EvolverBackend
from .codex import CodexBackend
from .claude_p import ClaudePBackend
from .task import TaskBackend

# Priority order for `auto` selection.
_AUTO_ORDER: list[type[EvolverBackend]] = [
    CodexBackend, ClaudePBackend, TaskBackend,
]

_BY_NAME: dict[str, type[EvolverBackend]] = {
    cls.name: cls for cls in _AUTO_ORDER  # type: ignore[attr-defined]
}


def available_backends() -> list[tuple[str, bool]]:
    """Return [(name, available), ...] for all known backends. For doctor."""
    return [(cls.name, cls().available()) for cls in _AUTO_ORDER]


def select_backend() -> EvolverBackend:
    """Apply the resolution rules. Always returns something (task is always
    available)."""
    pinned = userconfig.get("evolver.backend", "auto")
    if pinned != "auto":
        cls = _BY_NAME.get(pinned)
        if cls is not None:
            inst = cls()
            if inst.available():
                return inst
            # Pinned but not available → fall through to auto (worker will
            # log a warning).
    for cls in _AUTO_ORDER:
        inst = cls()
        if inst.available():
            return inst
    # Defensive: task is always available, but cover the impossible.
    return TaskBackend()

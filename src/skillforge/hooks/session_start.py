"""SessionStart hook.

Surface pending evolution work to the main agent. If the user is on the
`task` backend, this is the primary trigger for them to process the
queue. For codex/claude-p users, the queue should usually be empty by
the time they start a session (worker drained it asynchronously).
"""

from __future__ import annotations

from typing import Any

from ..evolver import queue


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    n = queue.count_pending()
    if n == 0:
        return None

    msg = (
        f"skillforge: {n} skill evolution{'s' if n != 1 else ''} queued. "
        f"Run /sf evolve (or `sf evolve` in Bash) to process — the "
        f"sf-evolve skill describes how."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg,
        }
    }

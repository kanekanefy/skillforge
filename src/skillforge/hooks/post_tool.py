"""PostToolUse hook — Phase 2 will record tool call outcomes here."""

from typing import Any


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    # Phase 1: no-op. Reserved for outcome recording in Phase 2.
    return None

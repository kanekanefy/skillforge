"""PreToolUse hook — Phase 2 will use this to tag Task tool prompts with skill_id."""

from typing import Any


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    # Phase 1: no-op. Reserved for skill-id injection in Phase 2.
    return None

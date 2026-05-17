"""UserPromptSubmit hook.

When the user submits a prompt, do a BM25 search against the local skill
registry and inject the top-K matches as system reminder context. The main
agent then decides whether to follow them.

Design notes:
  - We never block (no `permissionDecision: deny`). Hooks that can break
    a user's session are bad UX. We only ADD context.
  - Output schema follows Claude Code's hookSpecificOutput convention.
  - We cap the prompt at 400 chars before tokenizing — long prompts blow
    up FTS5's query parser and the user's intent is usually in the first
    sentence anyway.
"""

from __future__ import annotations

from typing import Any

from ..store import db

MAX_QUERY_CHARS = 400
TOP_K = 5
MIN_SCORE_DISPLAY = 5  # FTS bm25 is "lower = better" — anything beyond this is noise


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return None

    rows = db.search(prompt[:MAX_QUERY_CHARS], limit=TOP_K)
    if not rows:
        return None

    # Format compact, scannable list. The main agent should see this as
    # *suggestions*, not orders — wording matters.
    lines = [
        "skillforge: candidate skills matched against your prompt (BM25):"
    ]
    for r in rows:
        lines.append(f"  • [{r['name']}] {r['description']}")
    lines.append(
        "If any of these fit, follow the skill's pattern. "
        "Otherwise ignore — they're advisory only."
    )
    additional = "\n".join(lines)

    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional,
        }
    }

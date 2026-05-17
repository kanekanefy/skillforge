"""PreToolUse hook.

We care about Task tool calls specifically: that's where skill execution
happens. If the Task prompt contains an `sf-skill: <id-or-name>` marker
(the sf-orchestrate skill instructs the main agent to include this when
delegating to a candidate), we:

  1. Resolve the marker to a real skill_id (accept name or id).
  2. Bump total_selections + applied counters.
  3. Record into the task's active_skills.jsonl so post-task analysis
     can find it.

For any other tool, this is a no-op.
"""

from __future__ import annotations

from typing import Any

from ..recording import Recorder, current_task_id
from ..store import db
from ._protocol import find_skill_marker


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    tool_name = payload.get("tool_name") or payload.get("tool") or ""
    tool_input = payload.get("tool_input") or {}

    if tool_name != "Task":
        # Phase 2 only tracks Task tool. Other tools could be added later.
        return None

    # Task tool input shape (Claude Code): {description, prompt, subagent_type, ...}
    prompt_text = ""
    if isinstance(tool_input, dict):
        prompt_text = str(tool_input.get("prompt") or tool_input.get("description") or "")

    marker = find_skill_marker(prompt_text)

    rec = Recorder(current_task_id(payload))
    skill_id: str | None = None
    if marker:
        # Marker can be either skill_id or human-readable name; try both.
        with db.connect() as conn:
            row = conn.execute(
                "SELECT skill_id FROM skills "
                "WHERE (skill_id = ? OR name = ?) AND is_active = 1",
                (marker, marker)
            ).fetchone()
        if row:
            skill_id = row["skill_id"]
            db.bump_metrics(skill_id, total_selections=1, applied=1)
            rec.active_skill(skill_id, source="prompt_marker")

    rec.pre_tool(tool_name, tool_input if isinstance(tool_input, dict) else {}, skill_id)
    return None

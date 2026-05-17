"""PostToolUse hook.

For Task tool calls only: parse the subagent's response for the
<sf-outcome>{...}</sf-outcome> marker and update SQLite metrics
accordingly.

Outcome JSON shape (defined in sf-delegate SKILL.md):
    {
      "applied":   bool,   # did the subagent actually follow the skill's pattern
      "effective": bool,   # did following the skill produce a satisfactory result
      "fallback":  bool,   # did the subagent abandon the skill and improvise
      "skill_id":  str     # echoed back so we can attribute correctly
    }

Why all four fields: OpenSpace's evolution thresholds rely on the
distinction between "selected but not applied" (skill seemed wrong on
closer look) and "applied but ineffective" (skill is buggy). We need
both signals to know whether to FIX or DERIVED-enhance.
"""

from __future__ import annotations

from typing import Any

from ..recording import Recorder, current_task_id
from ..store import db
from ._protocol import parse_outcome


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    tool_name = payload.get("tool_name") or payload.get("tool") or ""
    if tool_name != "Task":
        return None

    # Claude Code uses tool_response in hook payloads; the SDK historically
    # used tool_output. Accept either.
    output = payload.get("tool_response") or payload.get("tool_output") or {}
    if isinstance(output, dict):
        text = str(output.get("content") or output.get("result") or "")
    else:
        text = str(output)

    outcome = parse_outcome(text)
    rec = Recorder(current_task_id(payload))
    rec.post_tool(tool_name, outcome)

    if not outcome:
        # No marker — subagent didn't cooperate. Phase 3's FIX evolution
        # will eventually catch this as "applied but uninstrumented" but
        # for now we just leave the selection counter alone.
        return None

    skill_id = outcome.get("skill_id")
    if not skill_id:
        return None

    deltas: dict[str, int] = {}
    # applied was already incremented in pre_tool. Only update derived signals.
    if outcome.get("effective") is True:
        deltas["effective"] = 1
    if outcome.get("fallback") is True:
        deltas["fallback"] = 1
        # A fallback retroactively means "applied" was wrong; OpenSpace
        # counts this as a separate dimension rather than decrementing.
    if deltas:
        db.bump_metrics(skill_id, **deltas)
    return None

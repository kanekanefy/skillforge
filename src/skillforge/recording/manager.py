"""Append-only JSONL recorder for per-task events.

The session_id passed by Claude Code is our task_id. If a hook payload
doesn't include one (rare, but defensive), we synthesize one from PID +
timestamp.

Layout per task:
    ~/.skillforge/records/<task_id>/
        agent_actions.jsonl    # PreToolUse + PostToolUse one line each
        prompts.jsonl          # UserPromptSubmit
        summary.json           # final task summary (written by Stop hook)
        active_skills.jsonl    # which skill_ids were touched (one per Task call)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .. import config


def current_task_id(payload: dict[str, Any]) -> str:
    """Derive a task_id from Claude Code's hook payload.

    Claude Code sends `session_id` on most hook events. We prefer that.
    Fallback to a PID-based fake so we never crash on degenerate input.
    """
    sid = payload.get("session_id")
    if isinstance(sid, str) and sid:
        return sid
    return f"local-{os.getpid()}-{int(time.time())}"


def task_dir(task_id: str) -> Path:
    d = config.records_dir() / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


class Recorder:
    """Tiny helper bound to a single task_id; methods append one JSONL line each.

    Hooks are stateless processes that fire and exit, so we don't keep
    file handles open. Each .append() does open/write/close.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.dir = task_dir(task_id)

    def _append(self, stream: str, record: dict[str, Any]) -> None:
        record.setdefault("ts", time.time())
        path = self.dir / f"{stream}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def prompt(self, prompt: str, candidates: list[dict[str, Any]]) -> None:
        self._append("prompts", {"event": "prompt", "prompt": prompt[:2000],
                                  "candidates": candidates})

    def pre_tool(self, tool_name: str, tool_input: dict[str, Any],
                 detected_skill_id: str | None = None) -> None:
        self._append("agent_actions", {
            "event": "pre_tool",
            "tool": tool_name,
            "skill_id": detected_skill_id,
            # Don't store full tool_input — could be huge / contain secrets.
            "input_keys": sorted(tool_input.keys()) if isinstance(tool_input, dict) else [],
        })

    def post_tool(self, tool_name: str, outcome: dict[str, Any] | None) -> None:
        self._append("agent_actions", {
            "event": "post_tool",
            "tool": tool_name,
            "outcome": outcome,
        })

    def active_skill(self, skill_id: str, source: str) -> None:
        """Record which skill_ids were touched by this task. `source` is one
        of: 'prompt_marker', 'orchestrator_choice', 'fallback'."""
        self._append("active_skills", {"skill_id": skill_id, "source": source})

    def summary(self, data: dict[str, Any]) -> None:
        """Write the final summary.json. Overwrites any previous."""
        (self.dir / "summary.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_active_skills(self) -> list[str]:
        """Return unique skill_ids that were active during this task."""
        path = self.dir / "active_skills.jsonl"
        if not path.exists():
            return []
        seen: dict[str, None] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                seen[json.loads(line)["skill_id"]] = None
            except (json.JSONDecodeError, KeyError):
                continue
        return list(seen)

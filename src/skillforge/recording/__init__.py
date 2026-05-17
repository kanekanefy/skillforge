"""Per-task event recording.

Each Claude Code session gets a task_id (derived from the session_id payload
field). We append events to ~/.skillforge/records/<task_id>/<stream>.jsonl
as hooks fire, then write a final summary.json on Stop.

The recorder is intentionally append-only and per-file: no locks needed
because each hook event is its own line, and concurrent writers in different
streams don't conflict.
"""

from .manager import Recorder, current_task_id, task_dir

__all__ = ["Recorder", "current_task_id", "task_dir"]

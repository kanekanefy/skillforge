"""Stop hook.

Called when the Claude Code main agent finishes responding to a user
prompt. Two responsibilities:

  1. Phase 2: write the task summary.json and update completion counters.
  2. Phase 3: detect evolution candidates and fire an async worker.

For now (Phase 2-3) we keep this lightweight — anything LLM-y goes via
async detached worker in Phase 3, never blocking the Stop hook.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .. import config
from ..recording import Recorder, current_task_id
from ..store import db


# Threshold rules — kept here as one source of truth so they show up in
# code review when someone tweaks them.
def _check_thresholds(metrics: dict) -> str | None:
    """Return evolution kind ('fix' / 'derived') or None.

    Rules ported from OpenSpace evolver.py:1574-1597 with the same
    semantics. Computed only when there's enough data (>= 3 selections).
    """
    total = metrics.get("total_selections", 0)
    if total < 3:
        return None
    applied = metrics.get("applied", 0)
    effective = metrics.get("effective", 0)
    fallback = metrics.get("fallback", 0)
    completed = metrics.get("completed_tasks", 0)
    containing = metrics.get("containing_tasks", 0) or 1

    applied_rate = applied / total if total else 0
    effective_rate = effective / applied if applied else 0
    fallback_rate = fallback / total if total else 0
    completion_rate = completed / containing if containing else 0

    if fallback_rate > 0.4 or (applied_rate > 0.4 and completion_rate < 0.35):
        return "fix"
    if effective_rate < 0.55 and applied_rate > 0.25:
        return "derived"
    return None


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    task_id = current_task_id(payload)
    rec = Recorder(task_id)
    active = rec.read_active_skills()

    # Containing-tasks counter: every skill touched during this task
    # gets +1 (denominator for completion_rate).
    # The outcome of the task itself we infer from payload — Claude Code
    # signals success via stop_hook_active=True with no error. We treat
    # any Stop event as "task completed" since we can't observe failures.
    for skill_id in active:
        db.bump_metrics(skill_id, containing_tasks=1, completed_tasks=1)

    # Capture-mode candidate: task completed but no skill was active.
    # Phase 3 will use this signal to extract a new skill from the trace.
    capture_candidate = bool(payload.get("prompt") or active) and not active

    # Write summary.json — finalize the record.
    rec.summary({
        "task_id": task_id,
        "active_skills": active,
        "capture_candidate": capture_candidate,
        "completed": True,
    })

    # ── Phase 3: enqueue evolution candidates & fire detached worker ──
    enqueued = _enqueue_evolutions(active, capture_candidate, task_id)
    if enqueued and _async_enabled():
        _fire_worker(task_id)
    return None


# ─────────────────────────────────────────────────────────────────────
# Phase 3 wiring
# ─────────────────────────────────────────────────────────────────────


def _enqueue_evolutions(active: list[str], capture_candidate: bool,
                        task_id: str) -> int:
    """Look up metrics + check thresholds for each active skill, queue
    candidates to ~/.skillforge/queue/evolve.jsonl and the evolve_queue
    SQL table. Returns count enqueued."""
    import time
    import uuid

    from ..evolver.queue import enqueue

    n = 0
    for skill_id in active:
        m = db.get_metrics(skill_id) or {}
        kind = _check_thresholds(m)
        if kind:
            enqueue(
                queue_id=str(uuid.uuid4()),
                kind=kind,
                skill_id=skill_id,
                candidate={
                    "skill_id": skill_id,
                    "kind": kind,
                    "metrics": m,
                    "trigger_task_id": task_id,
                    "ts": time.time(),
                },
            )
            n += 1
    if capture_candidate:
        enqueue(
            queue_id=str(uuid.uuid4()),
            kind="captured",
            skill_id=None,
            candidate={
                "skill_id": None,
                "kind": "captured",
                "trigger_task_id": task_id,
                "ts": time.time(),
            },
        )
        n += 1
    return n


def _async_enabled() -> bool:
    """Check if async evolution is on (config.toml [evolver].async_in_stop_hook)."""
    from .. import userconfig
    return userconfig.get("evolver.async_in_stop_hook", True)


def _fire_worker(task_id: str) -> None:
    """Spawn the async evolver worker detached from the Claude Code session.

    nohup + setsid + redirect stdio so the child outlives this Stop hook.
    """
    # Find our own CLI binary the same way `sf install` did.
    sf_cmd = sys.argv[0] if Path(sys.argv[0]).exists() else "sf"
    log = config.logs_dir() / "evolve.log"
    cmd = f"nohup {shlex.quote(sf_cmd)} _worker --task-id {shlex.quote(task_id)} >> {shlex.quote(str(log))} 2>&1 &"
    # subprocess.Popen with start_new_session True is the cleaner equivalent
    # of nohup+setsid; this also doesn't depend on a shell being available.
    try:
        subprocess.Popen(
            [sf_cmd, "_worker", "--task-id", task_id],
            stdout=open(log, "ab"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        # Worker spawn failed — never break the user's session over it.
        # Phase 3's `sf evolve` CLI command is the manual fallback.
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"failed to spawn worker: {exc}\n")

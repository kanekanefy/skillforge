"""Async evolution worker — fired from Stop hook (detached) or `sf evolve`.

Drains ~/.skillforge/queue/evolve.jsonl candidates one at a time:
  - select backend (codex / claude-p / task)
  - render prompt
  - call backend.run(prompt)
  - parse output
  - apply (FIX / DERIVED / CAPTURED)
  - update queue status

The worker is intentionally single-process to keep things simple. SQL
ATOMIC claim() prevents two workers from grabbing the same item if
someone starts two by accident.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from .. import config
from ..analyzer import render_evolution_prompt
from ..store import db
from . import queue
from .apply import apply_captured, apply_derived, apply_fix
from .backends import EvolveCandidate, EvolverBackend, select_backend
from .parser import parse_evolution_output


def _candidate_signature(c: dict[str, Any]) -> str:
    """Stable hash for anti-loop dedup.

    Same skill_id + same metric pattern (rounded to 0.1) → same signature.
    Once handled, won't retrigger for 7 days even if metrics drift slightly.
    """
    m = c.get("metrics") or {}
    rounded = {k: round(v / max(m.get("total_selections", 1), 1) * 10) / 10
               if isinstance(v, (int, float)) else v
               for k, v in m.items()
               if k in ("applied", "effective", "fallback", "completed_tasks")}
    payload = json.dumps({"skill_id": c.get("skill_id"),
                          "kind": c.get("kind"),
                          "metrics": rounded}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _recently_addressed(skill_id: str | None, signature: str,
                        ttl_seconds: int = 7 * 24 * 3600) -> bool:
    if not skill_id:
        return False
    with db.connect() as conn:
        row = conn.execute(
            "SELECT last_addressed_at FROM addressed_degradations "
            "WHERE skill_id = ? AND signature = ? "
            "AND strftime('%s','now') - strftime('%s', last_addressed_at) < ?",
            (skill_id, signature, ttl_seconds)
        ).fetchone()
    return row is not None


def _mark_addressed(skill_id: str | None, signature: str) -> None:
    if not skill_id:
        return
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO addressed_degradations "
            "(skill_id, signature, last_addressed_at) "
            "VALUES (?, ?, datetime('now'))",
            (skill_id, signature),
        )


async def _process_one(item: dict[str, Any], backend: EvolverBackend) -> None:
    candidate_data = item["candidate"]
    skill_id = candidate_data.get("skill_id")
    signature = _candidate_signature(candidate_data)
    queue_id = item["queue_id"]

    # Anti-loop check.
    if _recently_addressed(skill_id, signature):
        queue.mark_done(queue_id, error=None)
        _log(f"queue_id={queue_id} skipped (anti-loop, signature={signature})")
        return

    if not queue.claim(queue_id, backend.name):
        _log(f"queue_id={queue_id} already claimed elsewhere")
        return

    candidate = EvolveCandidate(
        queue_id=queue_id,
        kind=item["kind"],
        skill_id=skill_id,
        metrics=candidate_data.get("metrics", {}),
        trigger_task_id=candidate_data.get("trigger_task_id"),
        workdir=str(config.home()),
    )
    prompt = render_evolution_prompt(
        kind=candidate.kind,
        skill_id=candidate.skill_id,
        metrics=candidate.metrics,
        trigger_task_id=candidate.trigger_task_id,
    )

    _log(f"queue_id={queue_id} kind={candidate.kind} backend={backend.name} START")
    result = await backend.run(candidate, prompt)

    if result.deferred:
        _log(f"queue_id={queue_id} deferred by backend: {result.deferred_reason}")
        # Don't mark done — leave pending so /sf evolve can pick it up.
        # Release the claim.
        with db.connect() as conn:
            conn.execute(
                "UPDATE evolve_queue SET status='pending', backend=NULL "
                "WHERE queue_id = ?", (queue_id,)
            )
        return

    if not result.success:
        queue.mark_done(queue_id, error=result.error or "unknown backend failure")
        _log(f"queue_id={queue_id} FAILED: {result.error}")
        return

    decision = parse_evolution_output(result.content)
    if not decision.confirmed:
        queue.mark_done(queue_id, error=f"rejected: {decision.reject_reason}")
        _mark_addressed(skill_id, signature)
        _log(f"queue_id={queue_id} REJECTED: {decision.reject_reason}")
        return
    if not decision.ok:
        queue.mark_done(queue_id, error=f"parse: {decision.failure_reason or 'malformed output'}")
        _log(f"queue_id={queue_id} PARSE FAIL: {decision.failure_reason}")
        return

    # Apply the change.
    try:
        if candidate.kind == "fix":
            new_id = apply_fix(target_skill_id=candidate.skill_id or "",
                               decision=decision)
        elif candidate.kind == "derived":
            new_id = apply_derived(parent_skill_id=candidate.skill_id or "",
                                   decision=decision)
        elif candidate.kind == "captured":
            new_id = apply_captured(decision=decision)
        else:
            raise ValueError(f"unknown kind: {candidate.kind}")
    except Exception as exc:  # noqa: BLE001
        queue.mark_done(queue_id, error=f"apply: {exc}")
        _log(f"queue_id={queue_id} APPLY ERROR: {exc}")
        return

    _mark_addressed(skill_id, signature)
    queue.mark_done(queue_id)
    _log(f"queue_id={queue_id} DONE kind={candidate.kind} new_id={new_id} "
         f"cost=${result.cost_usd:.4f}")


async def drain_async(max_items: int | None = None) -> int:
    """Process pending evolution work. Returns count processed."""
    pending = queue.list_pending()
    if max_items:
        pending = pending[:max_items]
    if not pending:
        return 0
    backend = select_backend()
    _log(f"drain start: {len(pending)} pending, backend={backend.name}")
    n = 0
    for item in pending:
        try:
            await _process_one(item, backend)
            n += 1
        except Exception as exc:  # noqa: BLE001
            _log(f"queue_id={item.get('queue_id')} UNHANDLED: {exc}")
            queue.mark_done(item["queue_id"], error=f"unhandled: {exc}")
    return n


def drain(max_items: int | None = None) -> int:
    return asyncio.run(drain_async(max_items))


def _log(msg: str) -> None:
    config.ensure_layout()
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    with (config.logs_dir() / "evolve.log").open("a", encoding="utf-8") as f:
        f.write(line)

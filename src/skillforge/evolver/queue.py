"""Durable evolution work queue.

Dual storage:
  - JSONL file at ~/.skillforge/queue/evolve.jsonl  (durable, human-readable)
  - SQL table `evolve_queue`                         (queryable status)

Both are written atomically; the JSONL is the source of truth if they
disagree (it survives DB corruption). On startup, we resync SQL from JSONL.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .. import config
from ..store import db


def enqueue(*, queue_id: str, kind: str, skill_id: str | None,
            candidate: dict[str, Any]) -> None:
    """Append one work item to both stores. Idempotent on queue_id."""
    config.ensure_layout()
    path = config.queue_path()

    record = {
        "queue_id": queue_id,
        "kind": kind,
        "skill_id": skill_id,
        "candidate": candidate,
    }
    # JSONL append. We don't lock — multiple processes appending whole
    # lines to a regular file is safe on POSIX for line-buffered writes
    # under POSIX_FILE_SAFE_LINE_LIMIT (~4KB); our records are small.
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

    # Mirror to SQL for query convenience.
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO evolve_queue (queue_id, skill_id, kind, candidate) "
            "VALUES (?, ?, ?, ?)",
            (queue_id, skill_id, kind, json.dumps(candidate)),
        )


def list_pending() -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT queue_id, kind, skill_id, candidate, enqueued_at "
            "FROM evolve_queue WHERE status = 'pending' "
            "ORDER BY enqueued_at"
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            d["candidate"] = json.loads(d["candidate"])
        except json.JSONDecodeError:
            pass
        out.append(d)
    return out


def claim(queue_id: str, backend: str) -> bool:
    """Atomically transition a pending item to running. Returns True on success.

    Two workers racing for the same item: only one wins the UPDATE.
    """
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE evolve_queue SET status='running', backend=? "
            "WHERE queue_id=? AND status='pending'",
            (backend, queue_id),
        )
        return cur.rowcount > 0


def mark_done(queue_id: str, *, error: str | None = None) -> None:
    status = "failed" if error else "done"
    with db.connect() as conn:
        conn.execute(
            "UPDATE evolve_queue SET status=?, finished_at=datetime('now'), error=? "
            "WHERE queue_id=?",
            (status, error, queue_id),
        )


def count_pending() -> int:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM evolve_queue WHERE status='pending'"
        ).fetchone()
    return row["n"] if row else 0

"""Minimal MCP server speaking JSON-RPC 2.0 over stdio.

We intentionally do NOT depend on the `mcp` Python package, because:
  - It pulls in pydantic + anyio + httpx etc.
  - We only need ~5 methods; the protocol is simple JSON-RPC over stdio.
  - Keeping the runtime dep footprint small keeps install fast and the
    surface less prone to upstream breakage.

Protocol coverage (subset of MCP spec sufficient for tool consumers):
  initialize / initialized
  tools/list
  tools/call
  notifications/initialized (no-op)

Read more: https://modelcontextprotocol.io/specification/
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any, Callable

from .. import config
from ..store import db


# ── tool implementations ────────────────────────────────────────────


def _tool_search_skills(query: str, limit: int = 5) -> dict:
    """BM25 search over local skills."""
    rows = db.search(query, limit=limit)
    return {"results": [dict(r) for r in rows]}


def _tool_get_skill(skill_id: str) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM skills WHERE skill_id = ? OR name = ?",
            (skill_id, skill_id)
        ).fetchone()
    if not row:
        return {"error": f"not found: {skill_id}"}
    return {"skill": dict(row)}


def _tool_record_outcome(skill_id: str, applied: bool = False,
                         effective: bool = False, fallback: bool = False) -> dict:
    deltas: dict[str, int] = {"total_selections": 1}
    if applied:
        deltas["applied"] = 1
    if effective:
        deltas["effective"] = 1
    if fallback:
        deltas["fallback"] = 1
    db.bump_metrics(skill_id, **deltas)
    return {"ok": True, "skill_id": skill_id}


def _tool_list_metrics() -> dict:
    return {"metrics": db.all_metrics()}


def _tool_queue_evolve(kind: str, skill_id: str | None = None,
                       candidate: dict | None = None) -> dict:
    """Enqueue an evolution candidate. The actual drainer runs in Claude
    Code (Task tool path) or via codex/claude-p if configured there too."""
    from ..evolver import queue
    qid = str(uuid.uuid4())
    queue.enqueue(queue_id=qid, kind=kind, skill_id=skill_id,
                  candidate=candidate or {"kind": kind, "skill_id": skill_id,
                                          "ts": time.time()})
    return {"queue_id": qid, "kind": kind}


# Tool registry: name → (callable, json schema)
TOOLS: dict[str, tuple[Callable[..., dict], dict]] = {
    "search_skills": (_tool_search_skills, {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    }),
    "get_skill": (_tool_get_skill, {
        "type": "object",
        "properties": {"skill_id": {"type": "string"}},
        "required": ["skill_id"],
    }),
    "record_outcome": (_tool_record_outcome, {
        "type": "object",
        "properties": {
            "skill_id": {"type": "string"},
            "applied": {"type": "boolean", "default": False},
            "effective": {"type": "boolean", "default": False},
            "fallback": {"type": "boolean", "default": False},
        },
        "required": ["skill_id"],
    }),
    "list_metrics": (_tool_list_metrics, {
        "type": "object", "properties": {}, "required": [],
    }),
    "queue_evolve": (_tool_queue_evolve, {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["fix", "derived", "captured"]},
            "skill_id": {"type": "string"},
            "candidate": {"type": "object"},
        },
        "required": ["kind"],
    }),
}


# ── JSON-RPC plumbing ────────────────────────────────────────────────


SERVER_INFO = {"name": "skillforge-bridge", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"


def _response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle_request(msg: dict) -> dict | None:
    """Return a response dict, or None for notifications (no response)."""
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    # Notifications have no id; the protocol mandates no response.
    is_notification = req_id is None

    if method == "initialize":
        return _response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "capabilities": {"tools": {}},
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # no-op

    if method == "tools/list":
        tools = []
        for name, (_, schema) in TOOLS.items():
            tools.append({
                "name": name,
                "description": (_.__doc__ or "").strip().split("\n")[0],
                "inputSchema": schema,
            })
        return _response(req_id, {"tools": tools})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        entry = TOOLS.get(name)
        if not entry:
            return _error(req_id, -32601, f"unknown tool: {name}")
        func, _schema = entry
        try:
            result = func(**args)
        except TypeError as exc:
            return _error(req_id, -32602, f"invalid arguments: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _error(req_id, -32603, f"internal error: {exc}")
        # MCP wraps results in a content block list.
        return _response(req_id, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result,
        })

    if is_notification:
        return None
    return _error(req_id, -32601, f"unknown method: {method}")


def serve_stdio() -> None:
    """Run a JSON-RPC loop on stdin/stdout until EOF."""
    config.ensure_layout()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            # Per JSON-RPC spec, error with id=null is appropriate for parse errors.
            sys.stdout.write(json.dumps(_error(None, -32700, f"parse: {exc}")) + "\n")
            sys.stdout.flush()
            continue
        resp = _handle_request(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def handle_request_for_test(msg: dict) -> dict | None:
    """Public entrypoint for unit tests (skips stdio)."""
    return _handle_request(msg)

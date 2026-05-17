"""Phase 5 tests — visual, bridge MCP server, dashboard."""

from __future__ import annotations

import importlib
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture
def seeded_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sf-home"
    monkeypatch.setenv("SKILLFORGE_HOME", str(home))
    import skillforge.config
    importlib.reload(skillforge.config)
    import skillforge.store.db
    importlib.reload(skillforge.store.db)

    from skillforge.store import db
    db.init_schema()
    db.seed_dummies()
    return home


# ── visual ──────────────────────────────────────────────────────────


def test_build_vision_prompt_includes_path_and_question(tmp_path: Path) -> None:
    from skillforge.visual import build_vision_prompt

    img = tmp_path / "shot.png"
    img.write_bytes(b"fake-png-data")
    p = build_vision_prompt(image_path=img, question="What dialog is shown?")
    assert str(img.resolve()) in p
    assert "What dialog is shown?" in p
    assert "<sf-vision>" in p
    assert "Read tool" in p


def test_analyze_image_outcome_parses_marker() -> None:
    from skillforge.visual import analyze_image_outcome

    reply = """\
Looking at the image, I can see a permission denied dialog.

<sf-vision>{"answer": "macOS Gatekeeper warning for unsigned binary", "confidence": "high", "key_evidence": "lock icon + 'cannot be opened' text"}</sf-vision>
"""
    out = analyze_image_outcome(reply)
    assert out is not None
    assert out["confidence"] == "high"
    assert "Gatekeeper" in out["answer"]


def test_analyze_image_outcome_silent_on_missing_marker() -> None:
    from skillforge.visual import analyze_image_outcome
    assert analyze_image_outcome("no marker here") is None
    assert analyze_image_outcome("") is None


def test_analyze_image_outcome_silent_on_bad_json() -> None:
    from skillforge.visual import analyze_image_outcome
    assert analyze_image_outcome("<sf-vision>not json</sf-vision>") is None


# ── bridge (MCP server) ─────────────────────────────────────────────


def test_bridge_initialize_returns_protocol(seeded_home: Path) -> None:
    from skillforge.bridge.mcp_server import handle_request_for_test

    resp = handle_request_for_test({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    })
    assert resp is not None
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "skillforge-bridge"


def test_bridge_notifications_have_no_response(seeded_home: Path) -> None:
    from skillforge.bridge.mcp_server import handle_request_for_test

    # No id == notification per JSON-RPC.
    assert handle_request_for_test({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }) is None


def test_bridge_lists_5_tools(seeded_home: Path) -> None:
    from skillforge.bridge.mcp_server import handle_request_for_test

    resp = handle_request_for_test({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list",
    })
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"search_skills", "get_skill", "record_outcome",
                     "list_metrics", "queue_evolve"}


def test_bridge_search_skills_returns_results(seeded_home: Path) -> None:
    from skillforge.bridge.mcp_server import handle_request_for_test

    resp = handle_request_for_test({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "search_skills", "arguments": {"query": "sql"}},
    })
    assert "result" in resp
    structured = resp["result"]["structuredContent"]
    assert any(r["name"] == "sql-format" for r in structured["results"])


def test_bridge_record_outcome_updates_metrics(seeded_home: Path) -> None:
    from skillforge.bridge.mcp_server import handle_request_for_test
    from skillforge.store import db

    handle_request_for_test({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "record_outcome", "arguments": {
            "skill_id": "01HDEMO000000000000001",
            "applied": True, "effective": True,
        }},
    })
    m = db.get_metrics("01HDEMO000000000000001")
    assert m is not None
    assert m["applied"] == 1
    assert m["effective"] == 1


def test_bridge_queue_evolve_enqueues(seeded_home: Path) -> None:
    from skillforge.bridge.mcp_server import handle_request_for_test
    from skillforge.evolver import queue

    resp = handle_request_for_test({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "queue_evolve", "arguments": {
            "kind": "captured",
        }},
    })
    qid = resp["result"]["structuredContent"]["queue_id"]
    assert qid
    pending = queue.list_pending()
    assert any(p["queue_id"] == qid for p in pending)


def test_bridge_unknown_tool_errors(seeded_home: Path) -> None:
    from skillforge.bridge.mcp_server import handle_request_for_test

    resp = handle_request_for_test({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "nope", "arguments": {}},
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_bridge_bad_arguments_errors(seeded_home: Path) -> None:
    from skillforge.bridge.mcp_server import handle_request_for_test

    resp = handle_request_for_test({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "search_skills", "arguments": {"wrong_arg": "x"}},
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32602


# ── dashboard ───────────────────────────────────────────────────────


def test_dashboard_serves_overview_page(seeded_home: Path) -> None:
    from skillforge.dashboard.server import _Handler, get_free_port
    from http.server import ThreadingHTTPServer

    port = get_free_port(8800)
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.05)  # let the server bind
        for path in ("/", "/skills", "/metrics", "/queue", "/records"):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
                body = r.read().decode()
            assert r.status == 200
            assert "<html" in body.lower()
            assert "skillforge" in body
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def test_dashboard_404(seeded_home: Path) -> None:
    from skillforge.dashboard.server import _Handler, get_free_port
    from http.server import ThreadingHTTPServer

    port = get_free_port(8850)
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.05)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/nonexistent", timeout=2) as r:
            body = r.read().decode()
        assert "404" in body
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def test_dashboard_skill_detail(seeded_home: Path) -> None:
    from skillforge.dashboard.server import _Handler, get_free_port
    from http.server import ThreadingHTTPServer

    port = get_free_port(8900)
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.05)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/skill/01HDEMO000000000000001", timeout=2
        ) as r:
            body = r.read().decode()
        assert "sql-format" in body
        assert "Body" in body
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)

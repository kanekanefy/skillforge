"""Phase 2 hook behavior tests.

Cover the recording + metric tracking pipeline end-to-end at the function
level (no subprocess). Each test:
  1. Sets up a fresh isolated SKILLFORGE_HOME
  2. Seeds dummy skills
  3. Invokes pre_tool / post_tool / stop handlers with realistic payloads
  4. Inspects SQLite metrics + recorded jsonl
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def seeded_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sf-home"
    monkeypatch.setenv("SKILLFORGE_HOME", str(home))
    # Force module-level _OVERRIDE_HOME re-evaluation.
    import skillforge.config
    importlib.reload(skillforge.config)
    import skillforge.store.db
    importlib.reload(skillforge.store.db)

    from skillforge.store import db
    db.init_schema()
    db.seed_dummies()
    return home


def _task_payload(prompt_text: str, session_id: str = "test-task-1") -> dict:
    return {
        "session_id": session_id,
        "tool_name": "Task",
        "tool_input": {
            "description": "demo",
            "prompt": prompt_text,
            "subagent_type": "general-purpose",
        },
    }


def test_pre_tool_increments_on_skill_marker(seeded_home: Path) -> None:
    from skillforge.hooks.pre_tool import handle
    from skillforge.store import db

    payload = _task_payload("sf-skill: sql-format\n\nFormat this query...")
    handle(payload)

    m = db.get_metrics("01HDEMO000000000000001")
    assert m is not None
    assert m["total_selections"] == 1
    assert m["applied"] == 1
    assert m["effective"] == 0
    assert m["fallback"] == 0


def test_pre_tool_noop_without_marker(seeded_home: Path) -> None:
    from skillforge.hooks.pre_tool import handle
    from skillforge.store import db

    handle(_task_payload("just doing some unrelated work"))
    # No metrics row created
    assert db.get_metrics("01HDEMO000000000000001") is None


def test_pre_tool_ignores_non_task_tools(seeded_home: Path) -> None:
    from skillforge.hooks.pre_tool import handle
    from skillforge.store import db

    payload = {
        "session_id": "t",
        "tool_name": "Bash",
        "tool_input": {"command": "sf-skill: sql-format && ls"},
    }
    handle(payload)
    assert db.get_metrics("01HDEMO000000000000001") is None


def test_post_tool_parses_outcome_and_bumps(seeded_home: Path) -> None:
    """Full pre+post cycle: marker seen, outcome reported, metrics updated."""
    from skillforge.hooks.pre_tool import handle as pre
    from skillforge.hooks.post_tool import handle as post
    from skillforge.store import db

    pre(_task_payload("sf-skill: sql-format\nFormat please"))

    post_payload = {
        "session_id": "test-task-1",
        "tool_name": "Task",
        "tool_response": {
            "content": (
                "Here's the formatted SQL...\n\n"
                '<sf-outcome>{"applied":true,"effective":true,"fallback":false,'
                '"skill_id":"01HDEMO000000000000001"}</sf-outcome>'
            )
        },
    }
    post(post_payload)

    m = db.get_metrics("01HDEMO000000000000001")
    assert m["effective"] == 1
    assert m["fallback"] == 0


def test_post_tool_handles_fallback_signal(seeded_home: Path) -> None:
    from skillforge.hooks.pre_tool import handle as pre
    from skillforge.hooks.post_tool import handle as post
    from skillforge.store import db

    pre(_task_payload("sf-skill: sql-format\nDo it"))
    post({
        "session_id": "test-task-1",
        "tool_name": "Task",
        "tool_response": {
            "content": (
                "Started with the skill but had to improvise.\n"
                '<sf-outcome>{"applied":true,"effective":true,"fallback":true,'
                '"skill_id":"01HDEMO000000000000001"}</sf-outcome>'
            )
        },
    })
    m = db.get_metrics("01HDEMO000000000000001")
    assert m["effective"] == 1
    assert m["fallback"] == 1


def test_post_tool_silent_without_outcome_marker(seeded_home: Path) -> None:
    """Missing marker should not crash; selection is already recorded by pre."""
    from skillforge.hooks.pre_tool import handle as pre
    from skillforge.hooks.post_tool import handle as post
    from skillforge.store import db

    pre(_task_payload("sf-skill: sql-format\nDo it"))
    post({
        "session_id": "test-task-1",
        "tool_name": "Task",
        "tool_response": {"content": "I forgot to emit the marker."},
    })
    m = db.get_metrics("01HDEMO000000000000001")
    assert m["total_selections"] == 1
    assert m["effective"] == 0  # no signal recorded


def test_marker_resolves_by_skill_id_as_well_as_name(seeded_home: Path) -> None:
    from skillforge.hooks.pre_tool import handle
    from skillforge.store import db

    handle(_task_payload("sf-skill: 01HDEMO000000000000002\nGit work"))
    m = db.get_metrics("01HDEMO000000000000002")
    assert m and m["total_selections"] == 1


def test_stop_writes_summary_and_bumps_completion(seeded_home: Path) -> None:
    from skillforge.hooks.pre_tool import handle as pre
    from skillforge.hooks.stop import handle as stop
    from skillforge.store import db
    from skillforge import config

    pre(_task_payload("sf-skill: sql-format\nDo it"))
    stop({"session_id": "test-task-1", "prompt": "the user prompt"})

    m = db.get_metrics("01HDEMO000000000000001")
    assert m["completed_tasks"] == 1
    assert m["containing_tasks"] == 1

    summary_path = config.records_dir() / "test-task-1" / "summary.json"
    assert summary_path.exists()
    data = json.loads(summary_path.read_text())
    assert "01HDEMO000000000000001" in data["active_skills"]
    assert data["completed"] is True


def test_stop_marks_capture_candidate_when_no_skill_used(seeded_home: Path) -> None:
    """Task ran, succeeded, didn't touch any skill → CAPTURED candidate."""
    from skillforge.hooks.stop import handle as stop
    from skillforge import config

    stop({"session_id": "t-cap", "prompt": "do some novel work"})
    summary = json.loads((config.records_dir() / "t-cap" / "summary.json").read_text())
    assert summary["capture_candidate"] is True
    assert summary["active_skills"] == []


def test_threshold_check_triggers_fix_on_high_fallback() -> None:
    """The threshold function is the only deterministic piece of evolution
    triggering — lock it in with pure unit tests."""
    from skillforge.hooks.stop import _check_thresholds

    assert _check_thresholds({"total_selections": 5, "fallback": 3,
                              "applied": 4, "effective": 1,
                              "completed_tasks": 1, "containing_tasks": 5}) == "fix"

    assert _check_thresholds({"total_selections": 5, "fallback": 0,
                              "applied": 4, "effective": 1,
                              "completed_tasks": 4, "containing_tasks": 5}) == "derived"

    assert _check_thresholds({"total_selections": 5, "fallback": 0,
                              "applied": 4, "effective": 4,
                              "completed_tasks": 4, "containing_tasks": 5}) is None

    # Too little data to act on
    assert _check_thresholds({"total_selections": 2, "fallback": 2,
                              "applied": 2, "effective": 0}) is None

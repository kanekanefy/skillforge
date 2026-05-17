"""Phase 3 tests — evolver parser, backends, queue, applier.

We don't actually run codex/claude-p (those require real CLI auth).
We test:
  - parser.parse_evolution_output on real-shaped LLM outputs
  - apply_fix / apply_derived / apply_captured against a fresh DB
  - queue enqueue/claim/list_pending lifecycle
  - backend availability detection
  - threshold rules (already tested in phase 2 but worth re-running)
  - end-to-end with a mock backend that returns canned output
"""

from __future__ import annotations

import importlib
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


# ── parser ──────────────────────────────────────────────────────────


def test_parser_accepts_well_formed_output() -> None:
    from skillforge.evolver.parser import parse_evolution_output

    text = """CONFIRM_EVOLUTION: yes

Now I'll write the patched skill.

<skill-md>
This is the new body.
With multiple lines.
</skill-md>

EVOLUTION_COMPLETE
"""
    d = parse_evolution_output(text)
    assert d.confirmed
    assert "new body" in d.skill_md
    assert d.terminal == "complete"
    assert d.ok


def test_parser_handles_rejection() -> None:
    from skillforge.evolver.parser import parse_evolution_output

    text = "CONFIRM_EVOLUTION: no metrics are too noisy"
    d = parse_evolution_output(text)
    assert not d.confirmed
    assert "noisy" in d.reject_reason
    assert not d.ok


def test_parser_handles_failed_termination() -> None:
    from skillforge.evolver.parser import parse_evolution_output

    text = """CONFIRM_EVOLUTION: yes
<skill-md>partial draft</skill-md>
EVOLUTION_FAILED: ran out of context
"""
    d = parse_evolution_output(text)
    assert d.confirmed
    assert d.terminal == "failed"
    assert "context" in d.failure_reason
    assert not d.ok


def test_parser_empty_input() -> None:
    from skillforge.evolver.parser import parse_evolution_output
    assert not parse_evolution_output("").confirmed
    assert not parse_evolution_output("   \n  ").confirmed


# ── apply ───────────────────────────────────────────────────────────


def test_apply_fix_updates_in_place_and_archives_old(seeded_home: Path) -> None:
    from skillforge.evolver.apply import apply_fix
    from skillforge.evolver.parser import EvolutionDecision
    from skillforge.store import db

    decision = EvolutionDecision(
        confirmed=True,
        skill_md="Brand new improved body.",
        terminal="complete",
    )
    new_id = apply_fix(target_skill_id="01HDEMO000000000000001", decision=decision)
    assert new_id == "01HDEMO000000000000001"

    with db.connect() as conn:
        active = conn.execute(
            "SELECT body, version, origin FROM skills "
            "WHERE skill_id = ? AND is_active = 1",
            ("01HDEMO000000000000001",)
        ).fetchone()
        archived = conn.execute(
            "SELECT body FROM skills WHERE skill_id = ? AND is_active = 0",
            ("01HDEMO000000000000001__v1",)
        ).fetchone()
        lineage = conn.execute(
            "SELECT * FROM skill_lineage WHERE child_id = ?",
            ("01HDEMO000000000000001",)
        ).fetchall()

    assert active["body"] == "Brand new improved body."
    assert active["version"] == 2
    assert active["origin"] == "fixed"
    assert archived is not None
    assert "When the user shares a raw SQL" in archived["body"]
    assert len(lineage) == 1
    assert lineage[0]["kind"] == "fix"


def test_apply_derived_creates_new_child(seeded_home: Path) -> None:
    from skillforge.evolver.apply import apply_derived
    from skillforge.evolver.parser import EvolutionDecision
    from skillforge.store import db

    decision = EvolutionDecision(
        confirmed=True,
        skill_md="Enhanced SQL formatter with edge cases handled.",
        terminal="complete",
    )
    new_id = apply_derived(parent_skill_id="01HDEMO000000000000001", decision=decision)
    assert new_id != "01HDEMO000000000000001"

    with db.connect() as conn:
        new_row = conn.execute(
            "SELECT * FROM skills WHERE skill_id = ?", (new_id,)
        ).fetchone()
        lineage = conn.execute(
            "SELECT * FROM skill_lineage WHERE child_id = ?", (new_id,)
        ).fetchone()

    assert new_row["name"].endswith("-enhanced")
    assert new_row["origin"] == "derived"
    assert new_row["generation"] == 1
    assert lineage["kind"] == "derived"
    assert lineage["parent_id"] == "01HDEMO000000000000001"


def test_apply_captured_creates_fresh_skill(seeded_home: Path) -> None:
    from skillforge.evolver.apply import apply_captured
    from skillforge.evolver.parser import EvolutionDecision
    from skillforge.store import db

    decision = EvolutionDecision(
        confirmed=True,
        skill_md="""---
name: my-novel-skill
description: When the user wants to do X, run this novel pattern.
---

Step 1: do thing.
Step 2: do other thing.""",
        terminal="complete",
    )
    new_id = apply_captured(decision=decision)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM skills WHERE skill_id = ?", (new_id,)).fetchone()
    assert row["name"] == "my-novel-skill"
    assert "When the user wants" in row["description"]
    assert row["origin"] == "captured"
    assert row["generation"] == 0


def test_apply_captured_rejects_missing_frontmatter(seeded_home: Path) -> None:
    from skillforge.evolver.apply import apply_captured
    from skillforge.evolver.parser import EvolutionDecision

    decision = EvolutionDecision(
        confirmed=True,
        skill_md="No frontmatter here, just body text.",
        terminal="complete",
    )
    with pytest.raises(ValueError, match="frontmatter"):
        apply_captured(decision=decision)


# ── queue ───────────────────────────────────────────────────────────


def test_queue_enqueue_list_claim_done(seeded_home: Path) -> None:
    from skillforge.evolver import queue

    queue.enqueue(queue_id="q1", kind="fix", skill_id="01HDEMO000000000000001",
                  candidate={"skill_id": "01HDEMO000000000000001", "kind": "fix"})
    queue.enqueue(queue_id="q2", kind="captured", skill_id=None,
                  candidate={"skill_id": None, "kind": "captured"})

    pending = queue.list_pending()
    assert len(pending) == 2
    assert {item["queue_id"] for item in pending} == {"q1", "q2"}

    assert queue.claim("q1", backend="test") is True
    # Re-claiming the same id should fail.
    assert queue.claim("q1", backend="test") is False

    queue.mark_done("q1")
    assert queue.count_pending() == 1


# ── backend detection ──────────────────────────────────────────────


def test_task_backend_always_available() -> None:
    from skillforge.evolver.backends import TaskBackend
    assert TaskBackend().available() is True


def test_task_backend_returns_deferred() -> None:
    """Task backend should always defer — we test this is the contract."""
    import asyncio

    from skillforge.evolver.backends import TaskBackend
    from skillforge.evolver.backends.base import EvolveCandidate

    candidate = EvolveCandidate(queue_id="q", kind="fix", skill_id="s")
    result = asyncio.run(TaskBackend().run(candidate, "dummy prompt"))
    assert result.deferred is True
    assert result.success is True


def test_select_backend_falls_back_to_task_when_nothing_else_available(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force codex + claude-p unavailable, confirm we get task."""
    monkeypatch.setattr("skillforge.evolver.backends.codex.CodexBackend.available",
                        lambda self: False)
    monkeypatch.setattr("skillforge.evolver.backends.claude_p.ClaudePBackend.available",
                        lambda self: False)
    from skillforge.evolver.backends import select_backend
    assert select_backend().name == "task"


# ── prompts ─────────────────────────────────────────────────────────


def test_render_prompt_includes_skill_body(seeded_home: Path) -> None:
    from skillforge.analyzer import render_evolution_prompt

    p = render_evolution_prompt(
        kind="fix",
        skill_id="01HDEMO000000000000001",
        metrics={"total_selections": 5, "applied": 4, "effective": 0, "fallback": 3},
    )
    assert "FIX evolver" in p
    assert "sql-format" in p  # name
    assert "When the user shares a raw SQL" in p  # body
    assert "CONFIRM_EVOLUTION" in p
    assert "EVOLUTION_COMPLETE" in p


def test_render_prompt_captured_has_no_skill_section(seeded_home: Path) -> None:
    from skillforge.analyzer import render_evolution_prompt

    p = render_evolution_prompt(kind="captured", skill_id=None, metrics={})
    assert "CAPTURED evolver" in p
    assert "no trace available" in p  # no task_id provided
    assert "CONFIRM_EVOLUTION" in p


def test_render_prompt_unknown_kind_raises() -> None:
    from skillforge.analyzer import render_evolution_prompt
    with pytest.raises(ValueError):
        render_evolution_prompt(kind="bogus", skill_id=None, metrics={})


# ── worker end-to-end with mock backend ────────────────────────────


def test_worker_drain_with_mock_backend(seeded_home: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole pipeline: enqueue → drain → applied + queue marked done."""
    import asyncio
    from skillforge.evolver import queue as q, worker as w
    from skillforge.evolver.backends.base import EvolveResult, EvolverBackend
    from skillforge.store import db

    canned = """CONFIRM_EVOLUTION: yes

<skill-md>
Patched SQL formatter that handles edge case X.
</skill-md>

EVOLUTION_COMPLETE
"""

    class MockBackend(EvolverBackend):
        name = "mock"
        def available(self) -> bool:
            return True
        async def run(self, candidate, prompt):
            return EvolveResult(success=True, content=canned, backend_name=self.name)

    monkeypatch.setattr("skillforge.evolver.worker.select_backend",
                        lambda: MockBackend())

    q.enqueue(
        queue_id="q-mock-1", kind="fix", skill_id="01HDEMO000000000000001",
        candidate={
            "skill_id": "01HDEMO000000000000001",
            "kind": "fix",
            "metrics": {"total_selections": 5, "fallback": 3, "applied": 4},
            "trigger_task_id": None,
        },
    )

    n = w.drain()
    assert n == 1

    # Verify the skill was actually patched.
    with db.connect() as conn:
        row = conn.execute(
            "SELECT body, version, origin FROM skills "
            "WHERE skill_id = ? AND is_active = 1",
            ("01HDEMO000000000000001",)
        ).fetchone()
    assert row["origin"] == "fixed"
    assert row["version"] == 2
    assert "edge case X" in row["body"]

    assert q.count_pending() == 0


def test_worker_anti_loop_skips_recently_addressed(seeded_home: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Second drain on identical metrics should be skipped by anti-loop."""
    import asyncio
    from skillforge.evolver import queue as q, worker as w
    from skillforge.evolver.backends.base import EvolveResult, EvolverBackend

    canned = "CONFIRM_EVOLUTION: yes\n<skill-md>body</skill-md>\nEVOLUTION_COMPLETE"
    call_count = 0

    class CountingBackend(EvolverBackend):
        name = "mock"
        def available(self) -> bool:
            return True
        async def run(self, candidate, prompt):
            nonlocal call_count
            call_count += 1
            return EvolveResult(success=True, content=canned, backend_name=self.name)

    monkeypatch.setattr("skillforge.evolver.worker.select_backend",
                        lambda: CountingBackend())

    metrics = {"total_selections": 5, "fallback": 3, "applied": 4}
    candidate = {"skill_id": "01HDEMO000000000000001", "kind": "fix",
                 "metrics": metrics, "trigger_task_id": None}

    q.enqueue(queue_id="q1", kind="fix",
              skill_id="01HDEMO000000000000001", candidate=candidate)
    w.drain()
    assert call_count == 1

    # Re-enqueue same pattern → should hit anti-loop, not call backend.
    q.enqueue(queue_id="q2", kind="fix",
              skill_id="01HDEMO000000000000001", candidate=candidate)
    w.drain()
    assert call_count == 1  # unchanged

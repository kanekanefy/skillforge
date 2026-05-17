"""Unit tests for the UserPromptSubmit hook.

These lock in Phase 1 acceptance: BM25 returns relevant matches, ignores
stop-word noise, and never blocks the session.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def sf_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated skillforge state per test.

    We re-import config so its module-level _OVERRIDE_HOME picks up the new env.
    """
    home = tmp_path / "sf-home"
    monkeypatch.setenv("SKILLFORGE_HOME", str(home))
    # Force re-evaluation of config._OVERRIDE_HOME
    import skillforge.config
    importlib.reload(skillforge.config)
    import skillforge.store.db
    importlib.reload(skillforge.store.db)
    return home


@pytest.fixture
def seeded(sf_home: Path) -> Path:
    """sf_home with 3 dummy skills loaded."""
    from skillforge.store import db
    db.init_schema()
    db.seed_dummies()
    return sf_home


def _run_hook(prompt: str) -> dict | None:
    """Call the hook handler directly — no subprocess, faster + portable."""
    from skillforge.hooks.pre_prompt import handle
    return handle({"prompt": prompt})


def test_sql_prompt_surfaces_sql_format(seeded: Path) -> None:
    out = _run_hook("format my SELECT * FROM users sql query please")
    assert out is not None
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "[sql-format]" in ctx
    # sql-format should be first match
    lines = [l for l in ctx.splitlines() if l.startswith("  •")]
    assert lines[0].startswith("  • [sql-format]")


def test_git_prompt_surfaces_git_log(seeded: Path) -> None:
    out = _run_hook("summarize what we shipped this week from git history")
    assert out is not None
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "[git-log-explain]" in ctx


def test_json_prompt_surfaces_json_pretty(seeded: Path) -> None:
    out = _run_hook("this json output is unreadable, can you clean it up")
    assert out is not None
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "[json-pretty]" in ctx


def test_unrelated_prompt_silent(seeded: Path) -> None:
    """Stop-word filter should prevent false positives on irrelevant prompts."""
    assert _run_hook("what is the weather in tokyo?") is None


def test_empty_prompt_silent(seeded: Path) -> None:
    assert _run_hook("") is None


def test_hook_handler_handles_missing_keys_gracefully(seeded: Path) -> None:
    """Hook must not crash when payload is partial / unexpected shape."""
    from skillforge.hooks.pre_prompt import handle
    # No 'prompt' key → silent
    assert handle({}) is None
    # Non-string prompt → silent
    assert handle({"prompt": None}) is None

"""Filesystem paths and config loading.

Single source of truth for "where does skillforge live on disk".
Everything else imports from here so we never have hardcoded paths scattered.
"""

from __future__ import annotations

import os
from pathlib import Path

# Allow override via env for testing — useful in CI and the kick-off smoke test.
_OVERRIDE_HOME = os.environ.get("SKILLFORGE_HOME")


def home() -> Path:
    """Root of skillforge runtime state.

    Default: ~/.skillforge/
    Override with SKILLFORGE_HOME for tests/dev.
    """
    if _OVERRIDE_HOME:
        return Path(_OVERRIDE_HOME).expanduser().resolve()
    return Path.home() / ".skillforge"


def db_path() -> Path:
    """SQLite database path."""
    return home() / "db" / "skillforge.sqlite"


def skills_dir() -> Path:
    """Where installed skills live as <skill-id>/SKILL.md directories."""
    return home() / "skills"


def queue_path() -> Path:
    """JSONL queue of pending evolution candidates."""
    return home() / "queue" / "evolve.jsonl"


def records_dir() -> Path:
    """Per-task recording directories."""
    return home() / "records"


def logs_dir() -> Path:
    """Worker / hook log output."""
    return home() / "logs"


def cache_dir() -> Path:
    """Embedding cache, etc."""
    return home() / "cache"


def locks_dir() -> Path:
    """fcntl lock files."""
    return home() / "locks"


def config_path() -> Path:
    """User config (evolver backend, ranker, ...)."""
    return home() / "config.toml"


def ensure_layout() -> None:
    """Create all expected directories. Idempotent."""
    for d in (home(), db_path().parent, skills_dir(), queue_path().parent,
              records_dir(), logs_dir(), cache_dir(), locks_dir()):
        d.mkdir(parents=True, exist_ok=True)

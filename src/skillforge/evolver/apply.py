"""Apply parsed LLM output to the on-disk skill registry + SQLite.

Three modes, with different commit semantics:

  FIX      — replace existing skill.body in place; bump version; archive
             the old row as is_active=False; write a lineage entry.
  DERIVED  — create a NEW skill_id in a NEW directory; name = parent+'-enhanced';
             generation = max(parents.gen)+1; lineage.kind=derived.
  CAPTURED — create a NEW skill_id; name/description parsed from frontmatter;
             generation = 0; lineage empty.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from pathlib import Path
from typing import Any

from .. import config
from ..store import db
from .parser import EvolutionDecision


def _new_skill_id() -> str:
    """ULID-ish: 26 chars, time-sortable. Real ULID would need a dep; this
    is close enough for skill_id uniqueness."""
    ts = format(int(time.time() * 1000), "x").rjust(12, "0")[-12:]
    rand = secrets.token_hex(7)
    return f"01H{ts}{rand}".upper()[:26]


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_YAML_LINE_RE = re.compile(r"^([\w-]+):\s*(.*)$")


def _split_frontmatter(skill_md: str) -> tuple[dict[str, str], str]:
    """Very small YAML-frontmatter parser. We only need 'name' and 'description'."""
    m = _FRONTMATTER_RE.match(skill_md)
    if not m:
        return {}, skill_md
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        lm = _YAML_LINE_RE.match(line.strip())
        if lm:
            fm[lm.group(1)] = lm.group(2).strip().strip('"').strip("'")
    return fm, m.group(2).strip()


def apply_fix(*, target_skill_id: str, decision: EvolutionDecision) -> str:
    """Replace target skill's body. Return new skill_id (same as input;
    a FIX keeps the directory)."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM skills WHERE skill_id = ?", (target_skill_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"skill not found: {target_skill_id}")

    old_skill = dict(row)
    new_version = (old_skill["version"] or 1) + 1

    # Archive old row (is_active=0) keeping its rowid for history.
    archive_id = f"{target_skill_id}__v{old_skill['version']}"
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO skills "
            "(skill_id, name, description, tags, category, body, path, origin, "
            " version, generation, is_active, created_at) "
            "SELECT ?, name, description, tags, category, body, path, origin, "
            " version, generation, 0, created_at FROM skills WHERE skill_id = ?",
            (archive_id, target_skill_id),
        )
        # In-place update of the canonical row
        conn.execute(
            "UPDATE skills SET body = ?, version = ?, origin = 'fixed', "
            "updated_at = datetime('now') WHERE skill_id = ?",
            (decision.skill_md, new_version, target_skill_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO skill_lineage (child_id, parent_id, kind) "
            "VALUES (?, ?, 'fix')",
            (target_skill_id, archive_id),
        )

    # Persist to disk too (best-effort; the SQLite row is the source of truth)
    _write_skill_md(target_skill_id, old_skill["name"], old_skill["description"],
                    decision.skill_md)
    return target_skill_id


def apply_derived(*, parent_skill_id: str, decision: EvolutionDecision) -> str:
    """Create a new skill named '<parent>-enhanced' as a child."""
    with db.connect() as conn:
        parent = conn.execute(
            "SELECT * FROM skills WHERE skill_id = ?", (parent_skill_id,)
        ).fetchone()
    if parent is None:
        raise ValueError(f"parent not found: {parent_skill_id}")

    parent_d = dict(parent)
    new_id = _new_skill_id()
    new_name = f"{parent_d['name']}-enhanced"
    new_gen = (parent_d["generation"] or 0) + 1

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO skills (skill_id, name, description, tags, category, "
            "body, path, origin, version, generation, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'derived', 1, ?, 1)",
            (new_id, new_name, parent_d["description"], parent_d["tags"],
             parent_d["category"], decision.skill_md,
             str(config.skills_dir() / new_id / "SKILL.md"), new_gen),
        )
        conn.execute(
            "INSERT INTO skill_lineage (child_id, parent_id, kind) "
            "VALUES (?, ?, 'derived')",
            (new_id, parent_skill_id),
        )
    _write_skill_md(new_id, new_name, parent_d["description"], decision.skill_md)
    return new_id


def apply_captured(*, decision: EvolutionDecision) -> str:
    """Create a brand-new skill. Name + description come from frontmatter."""
    fm, body = _split_frontmatter(decision.skill_md)
    name = fm.get("name", "").strip()
    description = fm.get("description", "").strip()
    if not name or not description:
        raise ValueError(
            "captured skill missing required frontmatter fields 'name' or 'description'"
        )

    new_id = _new_skill_id()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO skills (skill_id, name, description, tags, category, "
            "body, path, origin, version, generation, is_active) "
            "VALUES (?, ?, ?, '', '', ?, ?, 'captured', 1, 0, 1)",
            (new_id, name, description, body,
             str(config.skills_dir() / new_id / "SKILL.md")),
        )
    _write_skill_md(new_id, name, description, body)
    return new_id


# ── disk persistence ────────────────────────────────────────────────


def _write_skill_md(skill_id: str, name: str, description: str, body: str) -> None:
    """Write SKILL.md to disk with proper frontmatter + cssk extension."""
    skill_dir = config.skills_dir() / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Frontmatter — use double quotes to be safe with colons/special chars.
    safe_desc = description.replace('"', '\\"')
    safe_name = name.replace('"', '\\"')
    content = f"""---
name: "{safe_name}"
description: "{safe_desc}"
cssk:
  skill_id: {skill_id}
---

{body}
"""
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

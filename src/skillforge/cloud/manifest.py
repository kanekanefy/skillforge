"""Registry index manifest — `index.json` schema.

The index is the source of truth for "what's available in this registry".
It's small (one entry per skill, ~300 bytes each) so a 1000-skill registry
is ~300KB — fetchable in one HTTP request.

Format (top-level dict for forward-compat):

    {
      "version": 1,
      "generated_at": "2026-05-18T...Z",
      "registry_name": "skillforge official",
      "skills": [
        {
          "skill_id": "01H...",
          "name": "sql-format",
          "description": "Format SQL queries ...",
          "category": "data",
          "tags": ["sql", "format"],
          "path": "skills/data/sql-format",
          "checksum": "sha256:...",
          "version": 1,
          "license": "Apache-2.0",
          "maintainer": "@user"
        },
        ...
      ]
    }
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class IndexEntry:
    skill_id: str
    name: str
    description: str
    category: str = ""
    tags: list[str] | None = None
    path: str = ""
    checksum: str = ""
    version: int = 1
    license: str = ""
    maintainer: str = ""

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["tags"] = d["tags"] or []
        return d


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _parse_frontmatter(skill_md: str) -> dict[str, Any]:
    """Tiny YAML frontmatter reader. Handles strings, lists [a,b,c], scalars."""
    m = _FRONTMATTER_RE.match(skill_md)
    if not m:
        return {}
    out: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if v.startswith("[") and v.endswith("]"):
            out[k] = [x.strip().strip('"').strip("'")
                      for x in v[1:-1].split(",") if x.strip()]
        else:
            out[k] = v
    return out


def _checksum(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def build_index(registry_root: Path, *, registry_name: str = "local",
                version: int = 1) -> dict[str, Any]:
    """Walk skills/<cat>/<name>/SKILL.md and build an index dict.

    Used by registry CI to regenerate index.json on PR merge.
    """
    import time

    entries: list[dict[str, Any]] = []
    skills_root = registry_root / "skills"
    if not skills_root.exists():
        return {"version": version, "registry_name": registry_name,
                "generated_at": _now(), "skills": []}

    for skill_md in sorted(skills_root.glob("*/*/SKILL.md")):
        rel_dir = skill_md.parent.relative_to(registry_root)
        category = skill_md.parent.parent.name
        content = skill_md.read_bytes()
        fm = _parse_frontmatter(content.decode("utf-8", "replace"))
        cssk = fm.get("cssk", {}) if isinstance(fm.get("cssk"), dict) else {}

        entries.append(IndexEntry(
            skill_id=str(cssk.get("skill_id") or fm.get("name") or skill_md.parent.name),
            name=fm.get("name") or skill_md.parent.name,
            description=fm.get("description", "").strip(),
            category=category,
            tags=fm.get("tags") or [],
            path=str(rel_dir),
            checksum=_checksum(content),
            version=int(cssk.get("version") or 1),
            license=fm.get("license", ""),
            maintainer=fm.get("maintainer", ""),
        ).to_json())

    return {
        "version": version,
        "registry_name": registry_name,
        "generated_at": _now(),
        "skills": entries,
    }


def load_index(index_text: str) -> list[IndexEntry]:
    """Parse an index.json into a list of entries. Tolerant of missing fields."""
    raw = json.loads(index_text)
    out: list[IndexEntry] = []
    for r in raw.get("skills", []):
        out.append(IndexEntry(
            skill_id=r.get("skill_id", r.get("name", "")),
            name=r.get("name", ""),
            description=r.get("description", ""),
            category=r.get("category", ""),
            tags=r.get("tags") or [],
            path=r.get("path", ""),
            checksum=r.get("checksum", ""),
            version=int(r.get("version", 1)),
            license=r.get("license", ""),
            maintainer=r.get("maintainer", ""),
        ))
    return out


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")

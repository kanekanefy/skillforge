"""Fetch + install from a remote registry.

We support two URL schemes for the registry:

  https://raw.githubusercontent.com/<owner>/<repo>/<branch>
      ↑ canonical. Treat as a base URL; index.json + skills/... are sub-paths.

  file:///absolute/path/to/registry
      ↑ local file:// URL for testing or air-gapped private registries.
      Same layout: <root>/index.json, <root>/skills/<cat>/<name>/SKILL.md

We never assume the network is available — every fetch can fall back to
a cached copy in ~/.skillforge/registry-cache/.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .. import config, userconfig
from ..store import db
from .manifest import IndexEntry, load_index

DEFAULT_REGISTRY = "https://raw.githubusercontent.com/skillforge-skills/registry/main"


def registry_url() -> str:
    """Resolve the active registry URL from config (with sensible default)."""
    return userconfig.get("registry.url", DEFAULT_REGISTRY) or DEFAULT_REGISTRY


def _cache_dir() -> Path:
    d = config.home() / "registry-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_bytes(url: str, timeout: float = 10.0) -> bytes:
    """GET a URL; supports both http(s):// and file:// without external deps."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "file":
        path = Path(urllib.parse.unquote(parsed.path))
        if not path.exists():
            raise FileNotFoundError(f"local registry path missing: {path}")
        return path.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "skillforge"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_index(*, use_cache_on_failure: bool = True) -> list[IndexEntry]:
    """Fetch + parse index.json from the active registry.

    Caches the raw bytes to ~/.skillforge/registry-cache/index.json on
    success. On network failure, falls back to that cache if present and
    `use_cache_on_failure` is True.
    """
    url = registry_url().rstrip("/") + "/index.json"
    cache = _cache_dir() / "index.json"
    try:
        raw = _fetch_bytes(url)
        cache.write_bytes(raw)
    except Exception as exc:
        if not use_cache_on_failure or not cache.exists():
            raise
        raw = cache.read_bytes()
    return load_index(raw.decode("utf-8", "replace"))


def install_skill(entry: IndexEntry, *, dest_root: Path | None = None,
                  verify_checksum: bool = True) -> Path:
    """Pull `entry.path/SKILL.md` from the registry, write to
    ~/.skillforge/skills/<skill_id>/SKILL.md, sync to SQLite.

    Returns the destination path.
    """
    base = registry_url().rstrip("/")
    skill_url = f"{base}/{entry.path}/SKILL.md"
    content = _fetch_bytes(skill_url)

    if verify_checksum and entry.checksum:
        got = "sha256:" + hashlib.sha256(content).hexdigest()
        if got != entry.checksum:
            raise ValueError(
                f"checksum mismatch for {entry.name}: "
                f"index={entry.checksum} actual={got}"
            )

    dest_root = dest_root or config.skills_dir()
    dest_dir = dest_root / entry.skill_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "SKILL.md"
    dest_path.write_bytes(content)

    # Mirror into SQLite so search picks it up immediately.
    from .manifest import _parse_frontmatter
    fm = _parse_frontmatter(content.decode("utf-8", "replace"))
    body = content.decode("utf-8", "replace")
    fm_end = body.find("\n---", 4)
    body_after_fm = body[fm_end + 4 :].lstrip() if fm_end > 0 else body

    tags_val = fm.get("tags") or []
    tags_str = " ".join(tags_val) if isinstance(tags_val, list) else str(tags_val)

    db.insert_skill(
        skill_id=entry.skill_id,
        name=entry.name,
        description=entry.description or fm.get("description", ""),
        tags=tags_str,
        category=entry.category,
        body=body_after_fm,
        path=str(dest_path),
        origin="original",
    )
    return dest_path


def publish_instructions(skill_id: str, *, registry_repo: str = "skillforge-skills/registry") -> str:
    """Return a multi-line string instructing the user how to PR a skill
    to the registry. We don't auto-run `gh pr create` because it requires
    interactive auth and we don't want to surprise the user.
    """
    return f"""\
To publish skill '{skill_id}' to {registry_repo}:

  1. Make sure `gh` CLI is installed and authenticated:
       gh auth status

  2. Fork the registry (one-time):
       gh repo fork {registry_repo} --clone --remote

  3. Copy your skill into the fork (replace <category>):
       mkdir -p registry/skills/<category>/{skill_id}
       cp ~/.skillforge/skills/{skill_id}/SKILL.md \\
          registry/skills/<category>/{skill_id}/SKILL.md

  4. Branch + commit + push + PR:
       cd registry
       git checkout -b add-{skill_id}
       git add skills/<category>/{skill_id}
       git commit -m "Add {skill_id}"
       git push -u origin add-{skill_id}
       gh pr create --fill

The registry's CI will regenerate index.json on merge.

Reminder: skills you publish are public. Don't include secrets, paths
to private files, or anything you wouldn't post on a public README.
"""

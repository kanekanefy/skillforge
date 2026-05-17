"""User-facing TOML config: ~/.skillforge/config.toml.

We expose a tiny dotted-key API (get/set) to avoid sprinkling TOML
parsing throughout the codebase. Values returned for missing keys come
from DEFAULTS so callers can always assume something sane.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from . import config

DEFAULTS: dict[str, Any] = {
    "evolver.backend": "auto",            # auto | codex | claude-p | task
    "evolver.async_in_stop_hook": True,
    "evolver.codex.extra_args": [],
    "evolver.claude_p.model": "claude-sonnet-4-5",
    "ranker.rerank": "none",              # none | embed | subagent
    "registry.url": "https://github.com/skillforge-skills/registry",
}


def _read_raw() -> dict[str, Any]:
    path = config.config_path()
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}


def _flatten(d: dict, prefix: str = "") -> dict[str, Any]:
    """Convert nested dict → dotted-key flat dict."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def get(key: str, default: Any | None = None) -> Any:
    flat = _flatten(_read_raw())
    if key in flat:
        return flat[key]
    if default is not None:
        return default
    return DEFAULTS.get(key)


def set_(key: str, value: Any) -> None:
    """Set a dotted key. We rewrite the file in our own tidy format.

    No tomli-w dependency: we hand-write the file. The grammar we support
    here is intentionally narrow — flat sections, no arrays-of-tables.
    """
    flat = _flatten(_read_raw())
    flat[key] = value
    _write_flat(flat)


def _write_flat(flat: dict[str, Any]) -> None:
    """Serialize flat dotted-key dict back to TOML, grouped by section."""
    # Group keys by their first dot-segment ("section").
    sections: dict[str, dict[str, Any]] = {}
    root: dict[str, Any] = {}
    for k, v in sorted(flat.items()):
        if "." in k:
            head, rest = k.split(".", 1)
            sections.setdefault(head, {})[rest] = v
        else:
            root[k] = v

    lines: list[str] = []
    for k, v in root.items():
        lines.append(f"{k} = {_toml_lit(v)}")
    if root:
        lines.append("")

    for section, items in sections.items():
        # Subsections (a.b) we render as [section.subsection] for cleanliness
        # but only one level deep — that's all we use.
        subgroups: dict[str | None, dict[str, Any]] = {None: {}}
        for k, v in items.items():
            if "." in k:
                sub, rest = k.split(".", 1)
                subgroups.setdefault(sub, {})[rest] = v
            else:
                subgroups[None][k] = v
        for sub, kvs in subgroups.items():
            if not kvs:
                continue
            header = f"[{section}.{sub}]" if sub else f"[{section}]"
            lines.append(header)
            for k, v in sorted(kvs.items()):
                lines.append(f"{k} = {_toml_lit(v)}")
            lines.append("")

    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _toml_lit(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_lit(x) for x in v) + "]"
    raise TypeError(f"unsupported TOML value type: {type(v).__name__}")

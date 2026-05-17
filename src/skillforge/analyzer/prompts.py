"""LLM prompt templates for FIX / DERIVED / CAPTURED evolution modes.

These prompts are sent to whichever backend (codex / claude-p) was chosen.
The LLM is expected to:
  1. Confirm whether evolution should proceed: emit
     `CONFIRM_EVOLUTION: yes` or `CONFIRM_EVOLUTION: no <reason>` as first line.
  2. If yes, produce a new SKILL.md (full file) wrapped in
     <skill-md>...</skill-md>.
  3. End with either `EVOLUTION_COMPLETE` or `EVOLUTION_FAILED: <reason>`.

The worker parses these tokens to decide what to commit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import config


def render_evolution_prompt(*, kind: str, skill_id: str | None,
                            metrics: dict[str, Any],
                            trigger_task_id: str | None = None) -> str:
    """Build the full prompt sent to a backend for one candidate."""
    if kind == "fix":
        return _fix_prompt(skill_id, metrics, trigger_task_id)
    if kind == "derived":
        return _derived_prompt(skill_id, metrics, trigger_task_id)
    if kind == "captured":
        return _captured_prompt(trigger_task_id)
    raise ValueError(f"unknown kind: {kind!r}")


# ── helpers ─────────────────────────────────────────────────────────


def _load_skill(skill_id: str | None) -> tuple[str, str]:
    """Return (current SKILL.md content, name) for a skill, or ('', '')."""
    if not skill_id:
        return "", ""
    from ..store import db
    with db.connect() as conn:
        row = conn.execute(
            "SELECT name, body, path FROM skills WHERE skill_id = ?", (skill_id,)
        ).fetchone()
    if not row:
        return "", ""
    return row["body"] or "", row["name"] or ""


def _load_recent_trace(task_id: str | None, max_lines: int = 200) -> str:
    """Get a compact view of the triggering task's recording."""
    if not task_id:
        return "(no trace available)"
    task_dir = config.records_dir() / task_id
    if not task_dir.exists():
        return "(trace directory missing)"
    parts: list[str] = []
    for stream in ("prompts", "agent_actions", "active_skills"):
        f = task_dir / f"{stream}.jsonl"
        if not f.exists():
            continue
        lines = f.read_text().splitlines()[-max_lines:]
        parts.append(f"## {stream}.jsonl\n" + "\n".join(lines))
    summary = task_dir / "summary.json"
    if summary.exists():
        parts.append(f"## summary.json\n{summary.read_text()}")
    return "\n\n".join(parts) if parts else "(empty trace)"


# ── FIX prompt ──────────────────────────────────────────────────────


def _fix_prompt(skill_id: str | None, metrics: dict[str, Any],
                task_id: str | None) -> str:
    body, name = _load_skill(skill_id)
    metrics_str = json.dumps(metrics, indent=2, default=str)
    trace = _load_recent_trace(task_id)
    return f"""\
You are skillforge's FIX evolver. The skill below has been failing in
real use and the metrics suggest it needs repair, not replacement.

# Skill to fix
name: {name}
skill_id: {skill_id}

## Current SKILL.md body
```
{body}
```

## Why we're here (quality metrics)
```json
{metrics_str}
```

## Recent failure trace (triggering task)
```
{trace}
```

# Your task

1. **Confirm or reject**. As your first line, output exactly one of:
   - `CONFIRM_EVOLUTION: yes` — proceed with the fix
   - `CONFIRM_EVOLUTION: no <one-line reason>` — abort; the metric pattern
     is a false alarm, the skill is fine

2. If you confirmed, produce the **complete corrected SKILL.md body**
   (no YAML frontmatter — just the body content) wrapped exactly like:

   ```
   <skill-md>
   ...corrected body...
   </skill-md>
   ```

3. End with exactly one of:
   - `EVOLUTION_COMPLETE` — fix produced
   - `EVOLUTION_FAILED: <reason>` — couldn't diagnose / repair

Guidelines:
- Preserve the skill's *intent*. A FIX changes implementation details,
  not the skill's purpose.
- Be specific about edge cases the failure trace revealed.
- If the skill is well-written but the trace shows the agent misapplied
  it, the fix is to tighten the description/triggers, not the body.
"""


# ── DERIVED prompt ──────────────────────────────────────────────────


def _derived_prompt(skill_id: str | None, metrics: dict[str, Any],
                    task_id: str | None) -> str:
    body, name = _load_skill(skill_id)
    metrics_str = json.dumps(metrics, indent=2, default=str)
    trace = _load_recent_trace(task_id)
    return f"""\
You are skillforge's DERIVED evolver. The skill below is OK but
consistently underperforming — the metrics show users follow it but it
doesn't always produce satisfactory results. Generate an **enhanced
descendant** in a new directory; do NOT modify the existing skill.

# Parent skill
name: {name}
skill_id: {skill_id}

## Current SKILL.md body
```
{body}
```

## Quality metrics
```json
{metrics_str}
```

## Recent execution trace
```
{trace}
```

# Your task

1. First line: `CONFIRM_EVOLUTION: yes` or `CONFIRM_EVOLUTION: no <reason>`.

2. If yes, produce a complete enhanced SKILL.md body wrapped:

   ```
   <skill-md>
   ...enhanced body...
   </skill-md>
   ```

   The enhancement should address the SPECIFIC weakness revealed by the
   metrics + trace. Don't just rewrite for style.

3. End with `EVOLUTION_COMPLETE` or `EVOLUTION_FAILED: <reason>`.

The new skill will be named `{name}-enhanced` and stored as a child of
the original. Its generation is parent.generation + 1.
"""


# ── CAPTURED prompt ─────────────────────────────────────────────────


def _captured_prompt(task_id: str | None) -> str:
    trace = _load_recent_trace(task_id)
    return f"""\
You are skillforge's CAPTURED evolver. A user completed a task
successfully WITHOUT using any of the locally-installed skills. Their
workflow is novel — your job is to distill it into a reusable skill.

## Successful task trace
```
{trace}
```

# Your task

1. First line: `CONFIRM_EVOLUTION: yes` or `CONFIRM_EVOLUTION: no <reason>`.
   Say no if the trace is too thin / one-off to generalize.

2. If yes, produce a complete SKILL.md with frontmatter wrapped:

   ```
   <skill-md>
   ---
   name: <kebab-case-name>
   description: <one sentence; clear enough to match similar future prompts>
   ---

   <body explaining when + how to apply this pattern>
   </skill-md>
   ```

3. End with `EVOLUTION_COMPLETE` or `EVOLUTION_FAILED: <reason>`.

Guidelines for a good CAPTURED skill:
- The name should be specific (not "do-helpful-thing").
- The description should READ like a trigger condition — "When the user
  asks to X, do Y."
- The body should capture the steps, NOT replay the exact commands of
  this one trace. Generalize.
"""

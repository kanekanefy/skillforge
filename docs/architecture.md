# Architecture

skillforge is **not a skill, it's a skill runtime** — a layer that sits on top of Claude Code via hooks, slash commands, system-level skills, SQLite state, and an async evolver worker.

## Layout

```
~/Desktop/project/skillforge/      ← code
~/.skillforge/                     ← runtime state
  ├── db/skillforge.sqlite         metrics + FTS5 index + lineage + queue
  ├── skills/<id>/SKILL.md         installed skills (CC-format compatible)
  ├── records/<task-id>/           per-task jsonl events + summary.json
  ├── queue/evolve.jsonl           durable evolution work queue
  ├── logs/evolve.log              async worker output
  ├── config.toml                  user settings (evolver backend, registry url)
  └── registry-cache/index.json    last successful fetch from registry
```

## Data flow

```
User prompt
   ↓
UserPromptSubmit hook
   ↓  (BM25 against ~/.skillforge/db/skillforge.sqlite FTS5 vtable)
   ↓
additionalContext injected into main agent
   ↓
Main agent picks a candidate, dispatches via Task tool
   ↓        (Task prompt embeds "sf-skill: <id>" marker)
PreToolUse hook
   ↓  (regex-extract marker, bump total_selections + applied counters)
Task subagent (isolated context)
   ↓  (instructed via sf-delegate to emit <sf-outcome>{json}</sf-outcome>)
PostToolUse hook
   ↓  (parse outcome, bump effective/fallback)
... task continues ...
   ↓
Stop hook (sync, <200ms)
   ↓  (read active_skills.jsonl, write summary.json,
   ↓   check thresholds → enqueue → spawn detached worker)
   ↓
   ╰─→ async sf _worker process
            ↓
            select_backend() → codex | claude-p | task
            ↓
            render evolution prompt → backend.run() → parse → apply
            ↓
            updates SQLite + writes new SKILL.md to disk
```

## Why hooks instead of MCP tools

skillforge could expose its functionality as an MCP server only. We chose hooks because they fire **automatically** on every prompt + every tool call. MCP tools require the main agent to actively choose to call them. With hooks, instrumentation is invisible: the main agent doesn't need to know skillforge exists, and skill-quality signal accumulates without explicit cooperation.

The MCP bridge (`sf bridge serve`) exists for **other** hosts (Codex, nanobot) that don't have Claude Code's hook system — they get read-write access via tools instead.

## Why a separate worker process

Stop hooks are synchronous. If we ran the LLM call for evolution inline, the user would stare at a frozen prompt for 5-10s after every prompt. By spawning a detached worker (`subprocess.Popen(start_new_session=True)`), the Stop hook returns in <200ms; the worker's output writes to `~/.skillforge/logs/evolve.log` and the new SKILL.md materializes on disk before the user's next prompt (usually).

This is also why the `task` backend exists as a fallback: it defers all evolution to a Task subagent dispatched from inside an active Claude Code session via `/sf evolve` — useful when neither `codex` nor `claude -p` is configured.

## What is "evolution"?

Three kinds, triggered by metric thresholds in `hooks/stop.py`:

| Kind | Trigger | Effect |
|---|---|---|
| `FIX` | `fallback_rate > 0.4` OR (`applied_rate > 0.4` AND `completion_rate < 0.35`) | Skill body replaced in place; version+1; old row archived `is_active=False`. |
| `DERIVED` | `effective_rate < 0.55` AND `applied_rate > 0.25` | New child skill with name `<parent>-enhanced`; generation+1; lineage row. |
| `CAPTURED` | Task completed without applying any skill | New skill with frontmatter parsed from subagent output; generation 0. |

The actual evolution prompts live in `src/skillforge/analyzer/prompts.py`. The applier in `src/skillforge/evolver/apply.py` enforces the version-bump + lineage rules atomically.

Anti-loop protection: a SHA256 of (skill_id + kind + rounded metric snapshot) is stored in `addressed_degradations` with a 7-day TTL. Same pattern recurring within 7 days is silently skipped.

## What's compatible / what's not

- Skill files (`SKILL.md` with YAML frontmatter) are **fully compatible** with Claude Code's native skill format. If you uninstall skillforge, your accumulated skills still work as plain skills.
- The `cssk:` frontmatter section (skill_id, version, parents, generation, origin) is an extension Claude Code ignores.
- skillforge is **bound to Claude Code's hook protocol**. If Anthropic changes the hook payload shape, skillforge will need an update.

## Why GitHub-as-cloud

`sf search --remote`, `sf install-skill`, `sf publish` all operate against a regular GitHub repo with `skills/<category>/<name>/SKILL.md` directories + a CI-generated `index.json`. No backend service to maintain, no operational cost, version history via git, PR review via standard GitHub flow. Forks let organizations run private registries.

See [evolver-backends.md](evolver-backends.md) and [evolution.md](evolution.md) for deeper dives.

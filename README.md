# skillforge

> A self-evolving skill runtime for Claude Code — search before you generate, learn from every task, evolve in real time.

skillforge is a Claude-Code-native rewrite of the ideas in [HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace): a *skill operating system* that watches what your agent does, ranks reusable patterns, and improves them automatically. Unlike OpenSpace, **all inference runs through your existing subscriptions** — no separate API key needed.

## Why

Claude Code can already load arbitrary skills from `~/.claude/skills/`. But:
- It doesn't track which skills get used (or whether they work).
- It doesn't search the skill library before generating — agents re-derive the same solutions over and over.
- There's no mechanism for a skill to *improve* based on how it's been performing.

skillforge fills those gaps by inserting itself between the user and the main agent via hooks, then running an async evolver that adapts the library over time.

## How

```
prompt → UserPromptSubmit hook  →  BM25 search ranks candidates
                                    additionalContext injects top-K into the main agent
                                                ↓
            main agent picks one,  →  PreToolUse hook bumps "selected" counter
            dispatches via Task tool          ↓
                                    PostToolUse hook parses <sf-outcome> marker
                                                ↓
              ...task completes...
                                                ↓
                                    Stop hook checks thresholds,
                                    spawns detached worker  →  evolves skill via
                                                                codex / claude-p / Task
```

Three pluggable evolver backends, picked based on what you already have:

| You have | Default evolver | Real-time? | Cash cost |
|---|---|---|---|
| ChatGPT Plus/Pro/Team | `codex exec --json` | ✅ | $0 |
| Anthropic API key | `claude -p` | ✅ | ~$0.05/evolution |
| Claude Code subscription only | Task tool (manual `/sf evolve`) | ❌ | $0 |

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/kanekanefy/skillforge/main/install.sh | bash
sf doctor
```

See [docs/quickstart.md](docs/quickstart.md) for a walk-through.

## Status

**v0.1.0 — Beta**. Single-developer project; the design is shaped by [docs/architecture.md](docs/architecture.md). All 6 phases of the [original plan](https://github.com/kane/dotfiles/blob/main/.claude/plans/skillforge.md) are implemented:

| Phase | Module | Status |
|---|---|---|
| 1 | hook pipeline + FTS5 search | ✅ |
| 2 | metric tracking + agent coordination protocol | ✅ |
| 3 | pluggable evolver (codex / claude-p / task) + async worker | ✅ |
| 4 | GitHub-backed community registry | ✅ |
| 5 | visual analysis + MCP cross-host bridge + dashboard | ✅ |
| 6 | install.sh + docs + CI | ✅ |

Test suite: 56 unit tests passing across all phases.

## Docs

- [Quickstart](docs/quickstart.md) — install, first run, configure
- [Architecture](docs/architecture.md) — data flow, design decisions
- [Skill format](docs/skill-format.md) — writing your own skills
- [Evolution](docs/evolution.md) — FIX / DERIVED / CAPTURED details
- [Evolver backends](docs/evolver-backends.md) — choosing codex vs claude-p vs task

## Commands

```
sf install [--scope user|project]    register hooks in settings.json
sf uninstall                          remove hooks
sf doctor                             comprehensive health check
sf list                               list installed skills
sf metrics show                       per-skill metric counters
sf search <query> [--remote]          BM25 search local + optional registry
sf install-skill <id>                 fetch a skill from the registry
sf publish <id>                       print PR instructions
sf evolve                             drain evolution queue manually
sf evolver doctor                     show which backend will be used
sf config get|set <key> [value]       user settings
sf dash                               localhost:7777 dashboard
sf bridge serve                       MCP server for other hosts
sf db init                            (re)create SQLite schema
sf seed                               load 3 demo skills (testing)
```

## What's different from a normal Claude Code skill?

A skill is passive content. skillforge is a runtime with hooks, SQLite state, lineage tracking, and an async evolver. Skills are how you *use* skillforge; skillforge is the system *managing* the skills.

If you remove skillforge tomorrow, your accumulated `~/.skillforge/skills/` are still valid Claude Code skills — the format is a strict superset.

## License

Apache-2.0

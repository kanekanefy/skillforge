<div align="center">

# 🔥 skillforge

**A self-evolving skill runtime for Claude Code — search before you generate, learn from every task, evolve in real time.**

[![CI](https://github.com/kanekanefy/skillforge/actions/workflows/ci.yml/badge.svg)](https://github.com/kanekanefy/skillforge/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kanekanefy/skillforge?display_name=tag&sort=semver&color=blue)](https://github.com/kanekanefy/skillforge/releases/latest)
[![License](https://img.shields.io/github/license/kanekanefy/skillforge?color=lightgrey)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-56%2F56_passing-brightgreen)](https://github.com/kanekanefy/skillforge/actions)
[![Code size](https://img.shields.io/github/languages/code-size/kanekanefy/skillforge?color=informational)](https://github.com/kanekanefy/skillforge)

[![Claude Code](https://img.shields.io/badge/built_for-Claude_Code-d97757?logo=anthropic&logoColor=white)](https://claude.com/claude-code)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-spec_compatible-6f1ec7)](https://github.com/anthropics/skills)
[![Self-evolving](https://img.shields.io/badge/skills-self--evolving-ff69b4)](docs/evolution.md)
[![No API key](https://img.shields.io/badge/no_API_key-needed-success)](docs/evolver-backends.md)

[Quickstart](docs/quickstart.md) · [Architecture](docs/architecture.md) · [Evolution](docs/evolution.md) · [Evolver backends](docs/evolver-backends.md)

</div>

---

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

## Where do skills come from?

You don't need to build your own library. **Anthropic released the Agent Skills spec as an open standard in Dec 2025**, and the ecosystem already has thousands of skills you can drop in:

| Source | What it is | How to use with skillforge |
|---|---|---|
| [anthropics/skills](https://github.com/anthropics/skills) | Anthropic's official skills repo | Clone individual `SKILL.md`s into `~/.skillforge/skills/<id>/` |
| [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | Anthropic-curated marketplace (~55 plugins) | Install via Claude Code's native `/plugin install`; skillforge will index whatever lands in `~/.claude/skills/` |
| [wshobson/agents](https://github.com/wshobson/agents) | Community marketplace (~72 plugins) | Same |
| [claudemarketplaces.com](https://claudemarketplaces.com/) | Discovery site (4200+ skills, 2500+ marketplaces) | Browse, install via Claude Code |
| [claudeskills.info](https://claudeskills.info/) | Skill-only marketplace | Browse, copy SKILL.md |
| [claude-plugins.dev](https://claude-plugins.dev/) | Community registry + CLI | Install plugins, skillforge tracks metrics on top |

**The Agent Skills spec is also adopted by OpenAI's Codex CLI** ([SkillsMP](https://skillsmp.com/) is cross-host), so skills you accumulate here are portable.

skillforge's role isn't to replace these registries — it's the **layer above them** that adds metrics + auto-evolution + cross-host bridging. Use whichever marketplace has the skills you want; skillforge tracks how they perform and improves them over time.

> ℹ️ Currently `sf install-skill` only knows skillforge's own registry format. To bring in skills from the marketplaces above, copy their `SKILL.md` into `~/.skillforge/skills/<some-id>/` and run `sf db init`. A `sf import` command for marketplace formats is on the v0.2 list.

## What's different from a normal Claude Code skill?

A skill is passive content. skillforge is a runtime with hooks, SQLite state, lineage tracking, and an async evolver. Skills are how you *use* skillforge; skillforge is the system *managing* the skills.

If you remove skillforge tomorrow, your accumulated `~/.skillforge/skills/` are still valid Claude Code skills — the format is a strict superset.

## License

Apache-2.0

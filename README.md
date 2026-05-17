# skillforge

> A self-evolving skill runtime for Claude Code — search before you generate, learn from every task, evolve in real time.

skillforge is what you get when you take [OpenSpace](https://github.com/HKUDS/OpenSpace)'s core insight ("agents waste tokens regenerating known solutions; let them learn") and rebuild it natively on Claude Code's primitives (Task tool, hooks, skills, slash commands).

## Status

🚧 **Phase 1 in progress** — not yet usable. See [docs/architecture.md](docs/architecture.md) and the [design plan](https://github.com/skillforge/skillforge/blob/main/docs/architecture.md) for what's coming.

## Why it exists

OpenSpace validated the idea but locks you into paying an external LLM API (OpenRouter / Anthropic API key). skillforge inverts the relationship: **all reasoning runs through your existing Claude Code / ChatGPT / Codex subscriptions**.

| You have | Default evolver | Real-time? | Cash cost |
|---|---|---|---|
| ChatGPT Plus/Pro | `codex exec --json` | ✅ | $0 |
| Anthropic API key | `claude -p` | ✅ | ~$0.05/evolution |
| Claude Code subscription only | Task tool (manual `/sf evolve`) | ❌ | $0 |

## What you'll get

1. **Search-before-generate**: BM25 (SQLite FTS5) over your skill library on every prompt
2. **Three auto-evolution modes** (FIX / DERIVED / CAPTURED) triggered by metric thresholds
3. **Real native context isolation** via Claude Code's Task tool
4. **GitHub-backed community registry** — no servers to host
5. **100% Claude Code skill-format compatible** — skillforge skills work as plain skills even without skillforge installed

See [docs/architecture.md](docs/architecture.md) for the full design.

## License

Apache-2.0

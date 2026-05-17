# Evolver backends

Evolution requires LLM reasoning. skillforge supports three backends to run it; pick based on what you already have configured.

## Decision tree

```
Do you have ChatGPT Plus / Pro / Team / Edu / Enterprise?
├── YES → use codex backend  (free under your subscription, real-time)
└── NO  → Do you have ANTHROPIC_API_KEY?
          ├── YES → use claude-p backend  (pay-per-token today, free after 2026-06-15
          │                                  if you're a Pro/Max subscriber)
          └── NO  → use task backend  (manual /sf evolve in Claude Code,
                                       no extra setup, no real-time)
```

`sf config set evolver.backend auto` (default) will probe each in order and pick the first available.

## codex

Invokes `codex exec --json` (OpenAI's Codex CLI). Auth is via ChatGPT subscription — run `codex login` once to set it up.

- **Cost**: $0, covered by your ChatGPT subscription
- **Real-time**: yes (Stop hook fires the worker; new skill on disk within ~10s)
- **Setup**: install Codex CLI from <https://developers.openai.com/codex>, then `codex login`
- **Model**: whatever Codex defaults to (currently GPT-5)
- **Rate limits**: ChatGPT subscription quotas apply

```bash
sf config set evolver.backend codex
sf evolver doctor   # should show ✓ codex
```

## claude-p

Invokes `claude -p <prompt> --output-format json` (Claude Code headless mode).

**Today** (before 2026-06-15): requires `ANTHROPIC_API_KEY` env var, pay-per-token at API pricing (~$0.03–0.10 per evolution at Sonnet rates).

**From 2026-06-15**: Pro/Max subscribers can claim a separate Agent SDK credit pool ($20 / $100 / $200 per month). Once that's live, `claude -p` becomes free up to the credit cap.

- **Cost**: today pay-per-token; later subscription credit
- **Real-time**: yes
- **Setup**: `export ANTHROPIC_API_KEY=sk-ant-...`, OR (after June 15) `sf config set evolver.claude_p.assume_subscription true`
- **Model**: configurable, default `claude-sonnet-4-5`

```bash
sf config set evolver.backend claude-p
sf config set evolver.claude_p.model claude-sonnet-4-5
```

## task

The no-CLI fallback. Stop hook enqueues candidates but doesn't fire a worker. Next time you're in a Claude Code session, the SessionStart hook surfaces a reminder: "N skills queued for evolution". You then run:

```
/sf evolve
```

(or `sf evolve` in Bash). The sf-evolve skill instructs the main agent to dispatch a Task subagent per item, render the prompt, capture the reply, and apply.

- **Cost**: covered by your Claude Code subscription (Task tool calls)
- **Real-time**: NO (evolution happens only when you run /sf evolve)
- **Setup**: none required
- **Pros**: zero external dependencies; only path that works on a sealed machine

## Switching backends

```bash
sf config set evolver.backend codex
sf config set evolver.backend claude-p
sf config set evolver.backend task
sf config set evolver.backend auto    # default — auto-detect

sf evolver doctor                     # see which one will be used right now
```

Backends can be switched at any time without re-installing or migrating state. Pending queue items get processed by whatever backend is active when the worker (or `sf evolve`) runs.

## Per-backend tuning

```toml
# ~/.skillforge/config.toml
[evolver.codex]
extra_args = []                       # e.g. ["--model", "gpt-5"]

[evolver.claude_p]
model = "claude-sonnet-4-5"
assume_subscription = false           # post-2026-06-15: set true
```

## Verifying backend output

After an evolution fires:

```bash
tail -n 50 ~/.skillforge/logs/evolve.log
sf evolve --list                       # what's still pending
sf metrics show                        # did the counters update
sf dash                                # /queue + /skills views
```

## When to switch off auto

```bash
sf config set evolver.async_in_stop_hook false
```

Use this if:
- You're debugging skillforge itself (you want to watch the queue grow without it draining)
- You're on a low-bandwidth machine and don't want every Stop to fire a background process
- You only want manual control over when evolution runs (privacy / cost-control)

You can still drain at will with `sf evolve`.

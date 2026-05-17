# Evolution

skillforge automatically improves your skill library based on real usage signals. There are three evolution modes.

## The three modes

### FIX — repair a broken skill

**Trigger**: A skill is being selected but failing.

```
fallback_rate > 0.4   OR   (applied_rate > 0.4 AND completion_rate < 0.35)
```

**Effect**: Replaces the skill's body in place. The previous version is archived (`is_active=False`) so you can always recover the history.

**Lineage**: One row in `skill_lineage` with `kind='fix'`. `skill_id` unchanged; `version` bumped.

### DERIVED — enhance an underperforming skill

**Trigger**: A skill is being applied but isn't producing satisfactory results often enough.

```
effective_rate < 0.55   AND   applied_rate > 0.25
```

**Effect**: Creates a NEW skill named `<parent>-enhanced` in a new directory. The original is unchanged.

**Lineage**: New `skill_id`, generation = max(parents.generation) + 1, lineage row with `kind='derived'`.

### CAPTURED — generalize a successful novel workflow

**Trigger**: A task completed successfully without applying any installed skill. Your novel pattern is worth saving.

**Effect**: New skill with name + description parsed from the analyzer's frontmatter output. No parents; generation 0.

## How it actually runs

1. **Stop hook** (synchronous, <200ms) — reads `active_skills.jsonl` for the just-finished task, checks thresholds against `skill_metrics`, enqueues candidates to `~/.skillforge/queue/evolve.jsonl`, and spawns a detached worker.

2. **Worker** (`sf _worker`) — selects the configured backend (codex / claude-p / task), renders the appropriate prompt (`analyzer/prompts.py`), runs the LLM, parses the output (`evolver/parser.py`), applies the change (`evolver/apply.py`).

3. **Anti-loop** — every triggered candidate gets a SHA256 signature based on (skill_id + kind + rounded metric snapshot). Same signature again within 7 days = skip.

## The prompt protocol

The backend's LLM is given a prompt that explicitly requires three structured outputs:

```
CONFIRM_EVOLUTION: yes              ← first line
                  no <reason>      ← OR this, to reject without changes

<skill-md>                          ← if confirmed
...new SKILL.md body...
</skill-md>

EVOLUTION_COMPLETE                  ← terminal
EVOLUTION_FAILED: <reason>          ← OR this
```

`parser.parse_evolution_output()` is permissive about whitespace and ordering but strict about the three tokens. Anything missing → silent reject (logged to `~/.skillforge/logs/evolve.log`).

## LLM confirmation gate

Note the `CONFIRM_EVOLUTION: yes/no` line is REQUIRED. This lets the LLM (which has full context: skill body + metrics + recent failure trace) **veto an evolution** the thresholds suggest. Pure threshold rules are brittle; combining them with LLM judgment cuts false positives sharply.

If the LLM says no, we record the signature as "addressed" anyway — same pattern won't re-trigger for 7 days, giving the metrics time to actually change before we revisit.

## Choosing what evolves

You can pin the backend or accept auto-detection:

```bash
sf config set evolver.backend auto         # default: codex > claude-p > task
sf config set evolver.backend codex        # use ChatGPT subscription
sf config set evolver.backend claude-p     # use Anthropic API key
sf config set evolver.backend task         # manual via /sf evolve in Claude Code
```

Or turn off async (debug mode):

```bash
sf config set evolver.async_in_stop_hook false   # don't auto-fire worker
```

Then drain manually:

```bash
sf evolve              # process up to all pending
sf evolve --max 1      # just one
sf evolve --list       # what's pending
```

## Manual override

You can always force-evolve a skill outside the auto-trigger:

```bash
# Inspect the queue
sf evolve --list

# Render the prompt that would be sent (for review)
sf evolve --render <queue_id>

# After running the prompt yourself, apply the output
sf evolve --apply <queue_id> --content output.txt
```

## Observing evolution

```bash
sf metrics show                      # current counters
tail -f ~/.skillforge/logs/evolve.log
sf dash                              # localhost:7777 → /queue and /skills/<id>
```

Each skill's detail page shows its full lineage tree.

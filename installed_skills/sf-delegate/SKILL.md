---
name: sf-delegate
description: Protocol for delegating skill execution to a Task subagent. Triggers when the main agent decides to follow one of the candidate skills surfaced by skillforge's UserPromptSubmit injection and the work warrants context isolation (multi-step, large file reads, exploratory tool use). Defines two required markers — the prompt-side `sf-skill:` reference and the response-side `<sf-outcome>` JSON — that let skillforge's hooks track which skills were used and how well.
---

# How to delegate skill work via Task tool

When you've picked a candidate skill from the BM25 injection and the work involves multiple grounding steps (file edits, command runs, web fetches, etc.), use the **Task tool** with the conventions below. This buys you:

- True context isolation: your main conversation doesn't fill up with intermediate trial-and-error
- Free metric tracking: skillforge counts the outcome automatically
- Parallel work: multiple `Task` calls in one message run concurrently

## Prompt-side: mark the skill you're following

In the Task tool's `prompt` parameter, include one line near the top:

```
sf-skill: <skill-id-or-name>
```

Use the bracketed name from the candidate injection (e.g. `sf-skill: sql-format`), OR the full skill_id ULID. Either works.

skillforge's `PreToolUse` hook reads this and increments `total_selections` + `applied` counters for the resolved skill.

## Response-side: emit an outcome marker

Instruct the subagent (via its prompt) to **end its response** with one `<sf-outcome>` line:

```
<sf-outcome>{"applied":true,"effective":true,"fallback":false,"skill_id":"sql-format"}</sf-outcome>
```

Field meanings (be honest — the data drives FIX/DERIVED/CAPTURED auto-evolution):

| field | when `true` |
|---|---|
| `applied` | The subagent actually followed the skill's pattern (vs. ignoring it) |
| `effective` | Following the skill produced a satisfactory result for the user's task |
| `fallback` | The subagent started with the skill but abandoned it midway and improvised |
| `skill_id` | Echo back the skill_id/name from the prompt marker |

A skill can be `applied=true, effective=false` (it was buggy or wrong). A skill can be `applied=false` (subagent decided on closer reading that the skill doesn't fit and used pure tools). A skill can be `applied=true, fallback=true, effective=true` (started on the skill, hit an edge case, improvised the rest successfully). All three are useful signals.

## Full Task prompt template

When you delegate, your Task `prompt` should look like:

```
sf-skill: <id>

[your task description / steps / context here]

When you finish, end your final response with exactly one line:
<sf-outcome>{"applied":true|false,"effective":true|false,"fallback":true|false,"skill_id":"<id>"}</sf-outcome>
Be honest about whether the skill's pattern actually fit and whether
the result is satisfactory. This data drives skillforge's evolution.
```

## When NOT to delegate

- Trivial tasks (one tool call, no exploration): just do it inline. Task spawning has overhead.
- The candidate is borderline: try it inline first; if it fails, then Task-delegate the re-attempt with `fallback:true` reported.
- The skill doesn't actually match: don't pretend to follow it just to feed the metrics. Better data signal is honest `applied:false`.

## Quick sanity examples

✅ Good: user asks "format this SQL", you delegate with `sf-skill: sql-format`, subagent applies the formatting rule, emits `{"applied":true,"effective":true,"fallback":false,"skill_id":"sql-format"}`.

✅ Good: user asks "summarize git history", you delegate with `sf-skill: git-log-explain`, subagent gets confused by `git log` output of a non-git directory, improvises an explanation from filesystem listing, emits `{"applied":true,"effective":true,"fallback":true,"skill_id":"git-log-explain"}` — honest about the fallback.

❌ Bad: user asks "what's the weather", no skill matches, you delegate anyway and pretend a skill fit. → corrupts metrics.

❌ Bad: subagent forgets to emit the outcome marker. → skillforge sees `applied:true` (from pre_tool) but no effectiveness signal, eventually triggers a spurious FIX. Always end with the marker.

---
name: sf-evolve
description: When skillforge has pending evolution work (you'll see a "skillforge: N skills queued for evolution" reminder at session start, or the user types /sf evolve), drain the queue using the Task tool. For each candidate, spawn a Task subagent with the appropriate evolution prompt (FIX/DERIVED/CAPTURED) and apply the result. Triggers on session start when queue is non-empty, or on explicit /sf evolve invocation.
---

# How to process pending evolution work

skillforge queues evolution candidates whenever the Stop hook detects a
skill quality issue or a CAPTURED opportunity. By default the queue is
drained by a detached background worker (codex or claude-p backend), but
when the user is on the `task` backend (no external CLI) the queue
accumulates until you process it from inside Claude Code.

## When you're triggered

You'll see one of:

  - A SessionStart reminder: "skillforge: N skills queued for evolution"
  - The user types `/sf evolve`

## The flow

For each item the user wants you to handle:

1. **Read the queue**: `Bash: sf evolve --list --json` returns pending items
   with `queue_id`, `kind`, `skill_id`, `metrics`, `trigger_task_id`.

2. **Per item, render the prompt**:
   `Bash: sf evolve --render <queue_id>` prints the prompt skillforge wants
   sent to the LLM. (This is the same prompt the codex/claude-p backends
   would use; consistency matters.)

3. **Spawn a Task subagent** with that prompt as the Task's `prompt`
   parameter. The subagent will return text containing:
     - `CONFIRM_EVOLUTION: yes|no`
     - `<skill-md>...</skill-md>` (if confirmed)
     - `EVOLUTION_COMPLETE` or `EVOLUTION_FAILED: <reason>`

4. **Submit the result** back:
   `Bash: sf evolve --apply <queue_id> --content <path-to-subagent-output>`
   skillforge parses the output, applies FIX / DERIVED / CAPTURED to the
   on-disk registry + SQLite, and marks the queue item done.

5. **After processing all items**, report briefly: "evolved N skills:
   <names>". Don't dump full SKILL.md content into the main conversation —
   that pollutes context for no benefit.

## Parallelism

Multiple Task calls in one message run in parallel. If you have 3 queue
items, spawn all 3 Task subagents in a single tool-call batch, then
apply each result.

## What if a subagent rejects evolution (`CONFIRM_EVOLUTION: no`)?

Pass the output to `sf evolve --apply` anyway. The CLI handles rejection
correctly: marks the queue item done with the rejection reason logged,
adds to anti-loop signatures so the same pattern won't re-queue for 7 days.

## Edge cases

- Empty queue: report "no pending evolutions" and stop.
- A queue item whose `trigger_task_id` no longer has a recording on disk:
  the evolution prompt will show "(trace directory missing)". Subagent
  should be told to reject with `CONFIRM_EVOLUTION: no insufficient trace`.
- More than ~5 items pending: process in batches of 3-5 to avoid
  overloading the main context.

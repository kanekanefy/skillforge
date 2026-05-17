---
name: sf-orchestrate
description: When skillforge has injected candidate skills (you'll see a "skillforge: candidate skills matched" system reminder), evaluate them against the user's request, pick the best fit if any, and follow that skill's pattern. If none fit, ignore them and proceed normally. Triggers on any user prompt that produced candidates.
---

# How to use skillforge candidates

When you receive a `<system-reminder>` of the form:

```
skillforge: candidate skills matched against your prompt (BM25):
  • [skill-name] short description
  • [skill-name] short description
```

…follow this flow:

1. **Evaluate fit silently.** For each candidate, ask yourself: does this skill's described pattern actually match what the user wants? BM25 retrieval is lexical — it surfaces things that share words, not necessarily things that match intent. Reject candidates that are surface-level matches but semantically off.

2. **If exactly one fits well**, mention it briefly and follow its pattern. Example:
   > Using the `sql-format` skill from your local registry. <proceeds to format>

3. **If multiple fit comparably**, pick the most specific. Mention which you chose and why, in one sentence.

4. **If none fit**, ignore the reminder entirely. Don't acknowledge it — that wastes the user's reading. Proceed as if it wasn't there.

5. **Never let candidates override the user's literal request.** They're suggestions about *how* to do what the user asked, never about *what* to do.

## Why this matters

skillforge tracks which skills get applied, and the metrics drive auto-evolution. If you mark something as "used" by following its pattern, that data feeds back into:
- FIX (skill repaired if it fails too often)
- DERIVED (new skill generated if existing one is consistently inadequate)
- CAPTURED (your novel workflow saved as a new skill if no candidate fit)

So your honest signal — "this skill helped" vs "this skill didn't fit" — is what makes the whole system smarter over time.

## Output convention (Phase 2+)

When skillforge's Phase 2 ships, you'll be asked to emit a structured outcome marker at the end of your reply when you used a candidate:

```
<sf-outcome>{"applied":true,"effective":true,"fallback":false,"skill_id":"01HDEMO000000000000001"}</sf-outcome>
```

For Phase 1, this is not yet enforced.

"""Cross-host MCP bridge.

Lets non-Claude-Code agents (Codex, OpenClaw, nanobot, …) consume
skillforge's local registry + metrics + queue WITHOUT being able to
trigger evolution (that requires the Claude Code Task tool path).

Run as: `sf bridge serve` → exposes stdio MCP server with these tools:
  - search_skills(query, limit)  → BM25 + remote results
  - get_skill(skill_id)          → full SKILL.md content
  - record_outcome(skill_id, applied, effective, fallback)  → update metrics
  - list_metrics()               → current metrics table
  - queue_evolve(kind, skill_id, candidate)  → enqueue (drainer still
    runs on the Claude Code side)

We use the stdlib only for the MCP protocol — there's a single optional
dependency (`mcp` package, already in our requirements) for the server
side. For Python ≥ 3.11.
"""

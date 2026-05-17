"""Skill evolution engine.

Triggered by the Stop hook when metric thresholds are crossed.
Architecture: a pluggable backend system (codex / claude-p / task) that
runs the actual LLM reasoning, with shared queue + lineage management
on top.
"""

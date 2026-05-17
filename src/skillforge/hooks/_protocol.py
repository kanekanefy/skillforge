"""Shared regex constants for the skillforge agent-coordination protocol.

We expect cooperating skills (sf-orchestrate, sf-delegate) to emit specific
markers that hooks can grep:

  - Active-skill marker (in Task prompts):
        sf-skill: <skill-id-or-name>
    Either the ULID or the human-readable name works; the parser tries both.

  - Outcome marker (in Task subagent responses):
        <sf-outcome>{"applied":true,"effective":true,"fallback":false,"skill_id":"..."}</sf-outcome>

If the marker is missing we degrade gracefully (still record selection but
without effectiveness signal).
"""

from __future__ import annotations

import json
import re

SF_SKILL_RE = re.compile(
    r"sf-skill:\s*([A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)

SF_OUTCOME_RE = re.compile(
    r"<sf-outcome>\s*(\{.*?\})\s*</sf-outcome>",
    re.DOTALL,
)


def find_skill_marker(text: str) -> str | None:
    """Extract the first sf-skill: marker from arbitrary text. None if missing."""
    if not text:
        return None
    m = SF_SKILL_RE.search(text)
    return m.group(1) if m else None


def parse_outcome(text: str) -> dict | None:
    """Find and parse the last <sf-outcome>...</sf-outcome> JSON.

    We take the LAST one because subagents sometimes echo examples earlier
    in their response and the authoritative one is at the end.
    """
    if not text:
        return None
    matches = SF_OUTCOME_RE.findall(text)
    if not matches:
        return None
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return None

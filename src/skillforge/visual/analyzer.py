"""Vision-capable Task prompt construction.

Why this isn't a "spawn vision subagent" function that calls Claude
directly: hooks can't dispatch the Task tool — only the main agent
loop can. So the role of this module is:

  1. Build a self-contained prompt the main agent can pass to Task
     verbatim. The prompt tells the subagent to use the Read tool
     to load the image (Claude Code's Read returns image bytes for
     .png/.jpg) and answer specific questions about it.
  2. Parse the structured response back when the main agent reports
     it via Bash → sf visual --record.

This keeps the visual layer aligned with the rest of skillforge: hooks
+ slash commands + Bash glue, no daemon, no extra runtime.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def build_vision_prompt(*, image_path: str | Path, question: str,
                        context_hint: str = "") -> str:
    """Render the prompt to give a Task subagent for vision analysis.

    The subagent is expected to:
      1. Read the image with the Read tool.
      2. Answer the question.
      3. End with `<sf-vision>{json}</sf-vision>` so the parent can parse.
    """
    p = Path(image_path).expanduser().resolve()
    # Build the context block separately — Python 3.11 doesn't allow
    # backslash-containing expressions inside f-strings (PEP 701 only).
    context_block = f"# Additional context\n{context_hint}\n\n" if context_hint else ""
    return f"""\
You are a vision-analysis subagent for skillforge.

# Task
Read the image at:
    {p}
(Use the Read tool; it returns image bytes that you can interpret
visually as part of your context.)

# Question
{question}

{context_block}# Output format
After reasoning, end your response with EXACTLY one line of the form:

    <sf-vision>{{"answer": "<concise text>", "confidence": "high|medium|low", "key_evidence": "<one short phrase>"}}</sf-vision>

Keep `answer` to <= 200 chars. The orchestrator parses the JSON; extra
prose before the marker is fine and ignored.
"""


_VISION_RE = re.compile(r"<sf-vision>\s*(\{.*?\})\s*</sf-vision>", re.DOTALL)


def analyze_image_outcome(subagent_response: str) -> dict | None:
    """Parse the <sf-vision> marker from a Task subagent's reply."""
    if not subagent_response:
        return None
    matches = _VISION_RE.findall(subagent_response)
    if not matches:
        return None
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return None

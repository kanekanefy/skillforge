"""Visual analysis helpers.

For tasks where a Tool output contains an image (screenshots from
playwright/chrome-devtools MCP, generated charts, etc.), this module
provides a small `analyze_image()` helper that wraps the construction
of a vision-capable Task subagent prompt. The actual LLM call happens
INSIDE the main agent via Task tool — we just hand it the right prompt.
"""

from .analyzer import build_vision_prompt, analyze_image_outcome

__all__ = ["build_vision_prompt", "analyze_image_outcome"]

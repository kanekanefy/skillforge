"""Hook handlers — invoked by Claude Code via the `sf hook <event>` CLI dispatcher.

Each module exports a single `handle(payload: dict) -> dict | None` function.
Returning None means "no output" (silent allow). Returning a dict gets
serialized to stdout as the hook's JSON response.
"""

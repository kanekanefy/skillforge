"""Stop hook — Phase 3 will trigger async evolver worker here."""

from typing import Any


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    # Phase 1: no-op. Reserved for evolution queueing + worker dispatch in Phase 3.
    return None

"""SessionStart hook — Phase 3 will surface pending evolution work here."""

from typing import Any


def handle(payload: dict[str, Any]) -> dict[str, Any] | None:
    # Phase 1: no-op. Reserved for evolution queue notifications in Phase 3.
    return None

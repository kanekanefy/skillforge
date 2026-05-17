"""Task tool backend — the no-CLI fallback.

We can't spawn a Task subagent from a detached worker (Task tool only
exists inside an active Claude Code main agent loop). So this backend
defers: it leaves the queue entry intact and tells the user to run
`/sf evolve` from inside Claude Code, which the main agent then dispatches
to a Task subagent.

It's "available" always — it requires nothing external. It's the
universal fallback when codex / claude-p aren't usable.
"""

from __future__ import annotations

from .base import EvolveCandidate, EvolveResult, EvolverBackend


class TaskBackend(EvolverBackend):
    name = "task"

    def available(self) -> bool:
        return True

    async def run(self, candidate: EvolveCandidate, prompt: str) -> EvolveResult:
        return EvolveResult.deferred_result(
            reason=(
                "task backend — queued for next Claude Code session. "
                "Run `/sf evolve` from inside the main agent to process."
            ),
            backend_name=self.name,
        )

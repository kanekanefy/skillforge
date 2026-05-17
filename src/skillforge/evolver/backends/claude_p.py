"""claude -p (Claude Code headless) backend.

Today: requires ANTHROPIC_API_KEY env var (pay-per-token).
After 2026-06-15: Pro/Max subscribers can claim a separate Agent SDK
credit pool that covers this.

`claude -p "<prompt>" --output-format json` returns a single JSON:
    {"type":"result","subtype":"success","result":"...","cost_usd":0.01,...}
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time

from ... import userconfig
from .base import EvolveCandidate, EvolveResult, EvolverBackend


class ClaudePBackend(EvolverBackend):
    name = "claude-p"

    def available(self) -> bool:
        if not shutil.which("claude"):
            return False
        # Auth check: ANTHROPIC_API_KEY OR (subscription credit available).
        # We can only check env directly; subscription credit detection
        # would require a probe call, which is expensive. Best-effort:
        # consider available if the env var is set, OR if the user
        # explicitly opted in via config.
        if os.environ.get("ANTHROPIC_API_KEY"):
            return True
        try:
            if userconfig.get("evolver.claude_p.assume_subscription", False):
                return True
        except Exception:
            pass
        return False

    async def run(self, candidate: EvolveCandidate, prompt: str) -> EvolveResult:
        model = userconfig.get("evolver.claude_p.model", "claude-sonnet-4-5")
        args = ["claude", "-p", prompt, "--output-format", "json"]
        if candidate.workdir:
            args += ["--cwd", candidate.workdir]
        if model:
            args += ["--model", model]

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300
            )
        except asyncio.TimeoutError:
            return EvolveResult.failure("claude -p timeout (300s)", self.name)
        except FileNotFoundError:
            return EvolveResult.failure("claude CLI not found", self.name)

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", "replace")[:2000]
            return EvolveResult.failure(f"claude exit {proc.returncode}: {err_text}",
                                        self.name)

        try:
            data = json.loads(stdout.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            return EvolveResult.failure(f"claude returned non-JSON: {exc}", self.name)

        if data.get("subtype") != "success":
            return EvolveResult.failure(
                f"claude reported subtype={data.get('subtype')}", self.name
            )

        elapsed = time.monotonic() - start
        return EvolveResult(
            success=True,
            content=str(data.get("result") or ""),
            cost_usd=float(data.get("total_cost_usd") or data.get("cost_usd") or 0),
            backend_name=f"{self.name} ({elapsed:.1f}s)",
        )

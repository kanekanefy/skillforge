"""Codex CLI backend.

Calls `codex exec --json "<prompt>"` and parses the JSONL event stream.
ChatGPT subscription covers the cost; no API key needed.

JSONL event shape (observed from `codex exec --json` empirically;
may need adjustment as the CLI evolves):
    {"type": "message_start", ...}
    {"type": "message_delta", "delta": {"text": "..."}}
    {"type": "result", "content": "...", "cost": 0.0}      ← we want this
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time

from .base import EvolveCandidate, EvolveResult, EvolverBackend


class CodexBackend(EvolverBackend):
    name = "codex"

    def available(self) -> bool:
        if not shutil.which("codex"):
            return False
        # Check auth without blocking too long. `codex auth status` is the
        # canonical command; falls back to `codex --help` exit 0 if the
        # status command isn't available in older versions.
        try:
            r = subprocess.run(
                ["codex", "auth", "status"],
                capture_output=True, timeout=5, check=False,
            )
            if r.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        # Best-effort fallback: assume installed = available.
        return True

    async def run(self, candidate: EvolveCandidate, prompt: str) -> EvolveResult:
        args = ["codex", "exec", "--json"]
        if candidate.workdir:
            args += ["--cd", candidate.workdir]
        args.append(prompt)

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
            return EvolveResult.failure("codex exec timeout (300s)", self.name)
        except FileNotFoundError:
            return EvolveResult.failure("codex CLI not found", self.name)

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", "replace")[:2000]
            return EvolveResult.failure(f"codex exit {proc.returncode}: {err_text}",
                                        self.name)

        content, cost = _parse_jsonl_events(stdout.decode("utf-8", "replace"))
        if not content:
            return EvolveResult.failure("codex returned no result event", self.name)

        elapsed = time.monotonic() - start
        return EvolveResult(
            success=True,
            content=content,
            cost_usd=cost,
            backend_name=f"{self.name} ({elapsed:.1f}s)",
        )


def _parse_jsonl_events(stream: str) -> tuple[str, float]:
    """Extract final content + cost from codex's JSONL output.

    We look for the LAST event matching either:
      - {"type": "result", "content": "..."}
      - {"type": "message_complete", "text": "..."}
      - {"type": "final_message", "message": "..."}
    Names vary across codex versions; we accept the most common shapes.
    """
    content = ""
    cost = 0.0
    for line in stream.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type", "")
        if t in ("result", "message_complete", "final_message"):
            content = (ev.get("content") or ev.get("text")
                       or ev.get("message") or content)
        if "cost" in ev and isinstance(ev["cost"], (int, float)):
            cost = max(cost, float(ev["cost"]))
        if t == "usage" and isinstance(ev.get("cost_usd"), (int, float)):
            cost = max(cost, float(ev["cost_usd"]))
    return content, cost

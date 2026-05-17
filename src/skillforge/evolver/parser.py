"""Parse LLM output from evolution backends.

Expected output shape (all three modes):

    CONFIRM_EVOLUTION: yes      (or 'no <reason>')

    ...some preamble...

    <skill-md>
    ...new SKILL.md content...
    </skill-md>

    EVOLUTION_COMPLETE          (or 'EVOLUTION_FAILED: <reason>')

We're permissive about whitespace and ordering. If CONFIRM is `no` we
return EvolutionDecision(confirmed=False).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_CONFIRM_RE = re.compile(r"CONFIRM_EVOLUTION:\s*(yes|no)\b\s*([^\n]*)", re.IGNORECASE)
_SKILLMD_RE = re.compile(r"<skill-md>\s*(.*?)\s*</skill-md>", re.DOTALL | re.IGNORECASE)
_TERMINAL_RE = re.compile(r"EVOLUTION_(COMPLETE|FAILED)(?::\s*([^\n]+))?", re.IGNORECASE)


@dataclass
class EvolutionDecision:
    confirmed: bool
    reject_reason: str = ""
    skill_md: str = ""
    terminal: str = ""                 # 'complete' | 'failed' | ''
    failure_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.confirmed and bool(self.skill_md) and self.terminal == "complete"


def parse_evolution_output(text: str) -> EvolutionDecision:
    if not text or not text.strip():
        return EvolutionDecision(confirmed=False, reject_reason="empty backend output")

    confirm = _CONFIRM_RE.search(text)
    if not confirm:
        # No explicit confirmation — be conservative, treat as rejection.
        return EvolutionDecision(confirmed=False,
                                 reject_reason="no CONFIRM_EVOLUTION line")

    if confirm.group(1).lower() == "no":
        reason = (confirm.group(2) or "").strip()
        return EvolutionDecision(confirmed=False,
                                 reject_reason=reason or "rejected by backend")

    skill_md = ""
    sm = _SKILLMD_RE.search(text)
    if sm:
        skill_md = sm.group(1).strip()

    terminal_kind = ""
    failure_reason = ""
    tm = _TERMINAL_RE.search(text)
    if tm:
        terminal_kind = tm.group(1).lower()
        if terminal_kind == "failed":
            failure_reason = (tm.group(2) or "").strip()

    return EvolutionDecision(
        confirmed=True,
        skill_md=skill_md,
        terminal=terminal_kind,
        failure_reason=failure_reason,
    )

"""Post-interview assessment on Groq.

ADR-004 routed this to Opus with thinking enabled, which was never validated
because the Anthropic account has no credit. This runs the same shape on the
free tier instead.

Unlike the interviewer loop, latency does not matter here — nobody is waiting
mid-conversation — so this asks for high reasoning effort and a large token
budget, and it is the one place in the codebase where that is the right call.
"""

from __future__ import annotations

import json
import logging

from groq import AsyncGroq

from prompts import ASSESSOR_PROMPT_VERSION, ASSESSOR_SYSTEM, assessor_user_prompt

log = logging.getLogger("intervueos.report")


class ReportGenerationError(RuntimeError):
    """Raised rather than returning a plausible-looking empty report."""


class GroqReportProvider:
    """Satisfies `providers.base.ReportProvider`."""

    prompt_version = ASSESSOR_PROMPT_VERSION

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = 4000,
        reasoning_effort: str = "high",
    ) -> None:
        self._client = AsyncGroq(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self.usage: dict | None = None

    async def assess(self, evidence: dict) -> dict:
        payload = json.dumps(evidence, ensure_ascii=False, indent=1)
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": ASSESSOR_SYSTEM},
                {"role": "user", "content": assessor_user_prompt(payload)},
            ],
            max_completion_tokens=self._max_tokens,
            temperature=0.3,
            reasoning_effort=self._reasoning_effort,
            reasoning_format="hidden",
            response_format={"type": "json_object"},
        )

        if u := getattr(resp, "usage", None):
            self.usage = {
                "input": getattr(u, "prompt_tokens", 0) or 0,
                "output": getattr(u, "completion_tokens", 0) or 0,
                "prompt_version": self.prompt_version,
            }

        raw = resp.choices[0].message.content or ""
        try:
            report = json.loads(raw)
        except json.JSONDecodeError as exc:
            # A truncated response is the likely cause; surface it rather than
            # shipping half a report.
            raise ReportGenerationError(
                f"assessor returned invalid JSON ({exc})"
            ) from exc

        return _validate(report, expected=len(evidence.get("exchanges", [])))


def _validate(report: dict, *, expected: int) -> dict:
    """Keep only what the schema promises, and refuse an empty assessment.

    The page renders whatever comes back, so a missing key must fail here
    rather than surface as a blank section the reader mistakes for a verdict.
    """
    if not isinstance(report, dict) or not report.get("headline"):
        raise ReportGenerationError("assessor returned no headline")

    per_q = report.get("per_question")
    if not isinstance(per_q, list) or not per_q:
        raise ReportGenerationError("assessor returned no per-question assessment")
    if len(per_q) != expected:
        log.warning(
            "assessor returned %d per-question entries, expected %d",
            len(per_q), expected,
        )

    def _list(key: str) -> list[str]:
        v = report.get(key)
        return [str(x) for x in v][:3] if isinstance(v, list) else []

    return {
        "headline": str(report["headline"]),
        "per_question": per_q,
        "strengths": _list("strengths"),
        "gaps": _list("gaps"),
        "advice": _list("advice"),
        "prompt_version": ASSESSOR_PROMPT_VERSION,
    }

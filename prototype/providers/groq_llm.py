"""Groq as the interviewer's voice.

Chosen over a frontier API for the in-loop turn because the loop is
latency-critical and Groq's inference is fast and free-tier eligible. Two
properties of the Anthropic provider do NOT carry over, and both are costed in
docs/COST_MODEL.md:

  * No prompt caching. The stable prefix (role + topics + JD + resume, ~4K
    tokens) is re-sent on every turn as a system message. On the free tier this
    costs nothing but tokens-per-minute headroom, which is the binding limit —
    see the TPM note below.
  * No `thinking` switch. Reasoning-style models on Groq may emit a reasoning
    preamble; we ask for none and defensively strip any that appears, because
    every fragment we yield goes straight to the TTS provider and would
    otherwise be spoken aloud.

The OpenAI-compatible Chat Completions shape is used, so this provider also
works against any OpenAI-compatible endpoint by changing `base_url`.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Sequence

from groq import AsyncGroq

from prompts import INTERVIEWER_PROMPT_VERSION, interviewer_system_prompt, turn_instruction

log = logging.getLogger("intervueos.llm")


class GroqInterviewerLlm:
    """Satisfies `providers.base.LlmProvider`.

    Constructor signature intentionally mirrors `AnthropicInterviewerLlm` so the
    two are interchangeable at the single construction site in `server.py`.
    """

    prompt_version = INTERVIEWER_PROMPT_VERSION

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        role: str,
        topics: list[str],
        job_description: str,
        resume: str,
        max_tokens: int = 160,
        temperature: float = 0.7,
        reasoning_effort: str = "low",
        state=None,
    ) -> None:
        self._client = AsyncGroq(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._state = state
        self._system = interviewer_system_prompt(role, topics, job_description, resume)
        self.usage: list[dict] = []

    async def generate(
        self, transcript: Sequence[tuple[str, str]], instruction: str
    ) -> AsyncIterator[str]:
        topic = self._state.current_topic if self._state else "the role"
        remaining = self._state.remaining if self._state else 0.0
        suffix = turn_instruction(instruction, topic, remaining)

        messages = [{"role": "system", "content": self._system}]
        messages.extend(_to_messages(transcript, suffix))

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_completion_tokens=self._max_tokens,
            temperature=self._temperature,
            reasoning_effort=self._reasoning_effort,
            reasoning_format="hidden",
            stream=True,
        )

        async for chunk in stream:
            # Groq reports usage on the final chunk under `x_groq`; this SDK
            # version has no OpenAI-style include-usage stream flag.
            if (xg := getattr(chunk, "x_groq", None)) is not None:
                if (u := getattr(xg, "usage", None)) is not None:
                    self.usage.append(
                        {
                            "input": getattr(u, "prompt_tokens", 0) or 0,
                            "output": getattr(u, "completion_tokens", 0) or 0,
                            "cache_read": 0,
                            "cache_write": 0,
                            "prompt_version": self.prompt_version,
                        }
                    )
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # Never speak a reasoning preamble: it goes straight to TTS.
            if getattr(delta, "reasoning", None):
                continue
            if delta.content:
                yield delta.content


def _to_messages(
    transcript: Sequence[tuple[str, str]], suffix: str
) -> list[dict]:
    """Map the conversation onto Chat Completions, collapsing consecutive
    same-role turns (a barge-in can leave two interviewer turns adjacent) and
    appending the volatile per-turn instruction as the final user message."""
    messages: list[dict] = []
    for speaker, text in transcript:
        role = "assistant" if speaker == "interviewer" else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + text
        else:
            messages.append({"role": role, "content": text})

    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + suffix
    else:
        messages.append({"role": "user", "content": suffix})
    return messages

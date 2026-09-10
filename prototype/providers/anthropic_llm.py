"""Claude as the interviewer's voice (ADR-004).

Latency-critical, so: thinking disabled, small max_tokens, and the entire
system prompt (role + topics + JD + resume) marked as a cache breakpoint. That
prefix is byte-identical on every turn of a session, so from turn two onward we
pay the cache-read rate on ~4K tokens instead of the input rate — see
COST_MODEL.md.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Sequence

from anthropic import AsyncAnthropic

from prompts import INTERVIEWER_PROMPT_VERSION, interviewer_system_prompt, turn_instruction

log = logging.getLogger("intervueos.llm")


class AnthropicInterviewerLlm:
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
        state=None,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._state = state
        self._system = interviewer_system_prompt(role, topics, job_description, resume)
        self.usage: list[dict] = []

    async def generate(
        self, transcript: Sequence[tuple[str, str]], instruction: str
    ) -> AsyncIterator[str]:
        topic = self._state.current_topic if self._state else "the role"
        remaining = self._state.remaining if self._state else 0.0
        suffix = turn_instruction(instruction, topic, remaining)

        messages = _to_messages(transcript, suffix)

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            thinking={"type": "disabled"},
            system=[
                {
                    "type": "text",
                    "text": self._system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

            final = await stream.get_final_message()
            u = final.usage
            self.usage.append(
                {
                    "input": u.input_tokens,
                    "output": u.output_tokens,
                    "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                    "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                    "prompt_version": self.prompt_version,
                }
            )


def _to_messages(
    transcript: Sequence[tuple[str, str]], suffix: str
) -> list[dict]:
    """Map the conversation onto the Messages API, collapsing consecutive
    same-role turns (a barge-in can leave two interviewer turns adjacent) and
    appending the volatile per-turn instruction *after* the cached prefix."""
    messages: list[dict] = []
    for speaker, text in transcript:
        role = "assistant" if speaker == "interviewer" else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"][0]["text"] += "\n" + text
        else:
            messages.append({"role": role, "content": [{"type": "text", "text": text}]})

    # The API needs the conversation to end on a user turn.
    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": []})
    messages[-1]["content"].append({"type": "text", "text": suffix})
    return messages

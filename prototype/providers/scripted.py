"""Test doubles.

These exist only so the orchestrator's turn-taking, barge-in, and speculation
logic can be tested deterministically without network calls or API keys. They
are never imported by the server.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterable, Sequence

from providers.base import SttEvent, TurnEvent


class ScriptedStt:
    """Replays a fixed list of SttEvents, with an optional pause between each so
    the orchestrator's tasks get a chance to run."""

    sample_rate = 16000

    def __init__(
        self,
        script: Iterable[SttEvent],
        gap: float = 0.01,
        tail: float = 0.4,
        lead: float = 0.0,
    ) -> None:
        self._script = list(script)
        self._gap = gap
        self._tail = tail
        self._lead = lead
        self.audio_received = 0

    async def __aenter__(self) -> "ScriptedStt":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def send_audio(self, pcm16: bytes) -> None:
        self.audio_received += len(pcm16)

    async def events(self) -> AsyncIterator[SttEvent]:
        # `lead` lets the interviewer's opening question finish before the
        # candidate is scripted to speak. Set it to 0 to test barge-in.
        await asyncio.sleep(self._lead)
        for ev in self._script:
            await asyncio.sleep(self._gap)
            yield ev
        # Let in-flight responses finish before the caller tears the session down.
        await asyncio.sleep(self._tail)


class RecordingTts:
    """Records the calls the orchestrator makes, and emits a byte of audio per
    character so `audio()` behaves like a real stream."""

    sample_rate = 24000

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.flushes = 0
        self.clears = 0
        self._out: asyncio.Queue = asyncio.Queue()

    async def __aenter__(self) -> "RecordingTts":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def speak(self, text: str) -> None:
        self.spoken.append(text)
        await self._out.put(text.encode())

    async def flush(self) -> None:
        self.flushes += 1

    async def clear(self) -> None:
        self.clears += 1
        while not self._out.empty():
            self._out.get_nowait()

    async def audio(self) -> AsyncIterator[bytes]:
        while True:
            yield await self._out.get()


class ScriptedLlm:
    """Yields a canned response, slowly enough to be cancelled mid-generation."""

    def __init__(self, response: str = "Why did you choose that approach?", delay: float = 0.02) -> None:
        self.response = response
        self.delay = delay
        self.calls: list[tuple[tuple, str]] = []
        self.cancelled = 0

    async def generate(
        self, transcript: Sequence[tuple[str, str]], instruction: str
    ) -> AsyncIterator[str]:
        self.calls.append((tuple(transcript), instruction))
        try:
            for word in self.response.split(" "):
                await asyncio.sleep(self.delay)
                yield word + " "
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


def turn(event: TurnEvent, transcript: str = "", index: int = 0) -> SttEvent:
    return SttEvent(event=event, transcript=transcript, turn_index=index)

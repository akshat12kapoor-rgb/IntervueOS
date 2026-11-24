"""Provider interfaces.

Everything vendor-specific lives behind these three Protocols. The orchestrator
in `session.py` imports nothing from any vendor module.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, Sequence, runtime_checkable


class TurnEvent(enum.Enum):
    """Turn-taking events, normalised across STT vendors.

    Deepgram Flux emits these natively. A Nova-3 + external-endpointer provider
    would synthesise them; a provider with no eager support simply never emits
    EAGER_END_OF_TURN / TURN_RESUMED and the orchestrator degrades to
    non-speculative generation.
    """

    START_OF_TURN = "start_of_turn"
    UPDATE = "update"
    EAGER_END_OF_TURN = "eager_end_of_turn"
    TURN_RESUMED = "turn_resumed"
    END_OF_TURN = "end_of_turn"


@dataclass(frozen=True, slots=True)
class Word:
    word: str
    start: float
    end: float
    confidence: float


@dataclass(frozen=True, slots=True)
class SttEvent:
    event: TurnEvent
    transcript: str
    turn_index: int
    words: Sequence[Word] = field(default_factory=tuple)
    end_of_turn_confidence: float = 0.0
    trigger: str = ""
    """On END_OF_TURN only. Deepgram reports whether the turn ended because
    the model was confident or because the silence timeout expired. A
    timeout-triggered turn is a multi-second dead pause for the candidate."""
    audio_window_start: float = 0.0
    audio_window_end: float = 0.0


@dataclass(frozen=True, slots=True)
class Utterance:
    """One thing the interviewer decided to say, plus the metadata the interview
    engine needs. `text` is the only part the candidate ever hears."""

    text: str
    should_end: bool = False


class SttProvider(Protocol):
    """Full-duplex streaming speech recognition with turn detection."""

    sample_rate: int

    async def __aenter__(self) -> "SttProvider": ...
    async def __aexit__(self, *exc: object) -> None: ...

    async def send_audio(self, pcm16: bytes) -> None:
        """Feed raw little-endian 16-bit mono PCM at `sample_rate`."""

    def events(self) -> AsyncIterator[SttEvent]:
        """Yield turn events until the stream closes."""


class TtsProvider(Protocol):
    """Streaming text-to-speech that can be interrupted mid-utterance."""

    sample_rate: int

    async def __aenter__(self) -> "TtsProvider": ...
    async def __aexit__(self, *exc: object) -> None: ...

    async def speak(self, text: str) -> None:
        """Queue text for synthesis. May be called repeatedly to stream a
        response sentence-by-sentence before generation has finished."""

    async def flush(self) -> None:
        """Signal end of utterance; synthesise whatever is buffered."""

    async def clear(self) -> None:
        """Barge-in. Discard buffered text and any audio not yet sent."""

    def audio(self) -> AsyncIterator[bytes]:
        """Yield raw little-endian 16-bit mono PCM at `sample_rate`."""


@runtime_checkable
class LlmProvider(Protocol):
    """Generates the interviewer's next spoken turn.

    Must be cancellable: `generate` is run as an asyncio task that the
    orchestrator cancels on barge-in or on TURN_RESUMED.
    """

    async def generate(
        self, transcript: Sequence[tuple[str, str]], instruction: str
    ) -> AsyncIterator[str]:
        """Stream the spoken response in fragments.

        `transcript` is an ordered sequence of (speaker, text) where speaker is
        "interviewer" or "candidate". `instruction` is the deterministic
        objective the interview engine chose for this turn — the LLM decides
        *how* to say it, not *what* to pursue.
        """


class ReportProvider(Protocol):
    """Judges a finished interview. Not latency-critical, quality-critical.

    The opposite of `LlmProvider` in every tuning dimension: it may think, it
    may take seconds, and it is called exactly once per interview. It is given
    the deterministic evidence record from `report.py`, never a raw transcript.
    """

    async def assess(self, evidence: dict) -> dict:
        """Return the assessment object described in `prompts.assessor_user_prompt`.

        Must raise rather than invent on failure — a fabricated report is worse
        than a missing one.
        """

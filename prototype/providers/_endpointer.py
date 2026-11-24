"""Local voice-activity endpointer: the thing Deepgram Flux gave us for free.

Flux decides a turn is over using the *words* — it is a speech model with turn
detection trained in, so it can tell "I used Postgres because" (still going)
from "I used Postgres" (done). A VAD cannot. A VAD sees energy and spectral
shape, so all it can answer is "is someone making a speech-like noise right
now", and a turn boundary has to be inferred from a long enough gap.

That difference is the entire cost of leaving Deepgram, and it lands in two
places:

* **Latency.** Flux's measured median end-of-turn lag was 1295 ms at
  `eot_threshold=0.5` (docs/LATENCY.md). Here the floor is `end_silence_ms`,
  because we cannot be confident until the silence has actually elapsed. Too
  short and we cut the candidate off mid-thought; too long and the interviewer
  feels slow.
* **No speculation.** `EAGER_END_OF_TURN` is a *semantic* guess — Flux saying
  "that sounded like a complete thought". Silence duration carries no such
  signal: at 300 ms a VAD knows nothing it will not also know at 700 ms, except
  less. Synthesising an eager event from a shorter silence threshold would fire
  on every ordinary mid-sentence breath, and every false fire costs a discarded
  draft *and* a `TURN_RESUMED` the orchestrator has to unwind. So this
  endpointer emits no eager event, and `SttProvider`'s contract then degrades
  the orchestrator to non-speculative generation. See ADR-009.

Deliberately synchronous, pure, and network-free: the turn-taking rules are the
part most likely to need tuning against recorded audio, and they are far easier
to tune when they can be unit-tested frame by frame.
"""

from __future__ import annotations

import collections
import enum
from dataclasses import dataclass


class Decision(enum.Enum):
    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"


@dataclass(frozen=True, slots=True)
class Boundary:
    decision: Decision
    audio: bytes
    """On SPEECH_ENDED, the complete turn audio including pre-roll. Empty on
    SPEECH_STARTED — the audio is still arriving."""
    speech_s: float
    """Seconds of audio in `audio`. Summed over a session, this — not wall
    clock — is what Groq bills against the audio-seconds-per-hour limit."""
    forced: bool = False
    """True when the turn was cut at `max_turn_s` rather than at a real pause."""


class SpeechGate:
    """The minimal interface the endpointer needs from a VAD.

    Exists so the state machine can be tested with a deterministic stub, and so
    Silero can be dropped in later without touching it.
    """

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:  # pragma: no cover
        raise NotImplementedError


class WebrtcGate:
    """`webrtcvad` behind `SpeechGate`.

    `aggressiveness` is 0-3; 3 filters the most non-speech. 2 is the default
    here because this runs on a candidate's laptop microphone in an unknown
    room: 3 starts clipping quiet sentence openings, and a clipped opening word
    reaches Whisper as a missing word — worse than a little extra silence.
    """

    def __init__(self, aggressiveness: int = 2) -> None:
        try:
            import webrtcvad
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "STT_PROVIDER=groq needs the webrtcvad-wheels package "
                "(pip install -r requirements.txt)."
            ) from exc
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return self._vad.is_speech(frame, sample_rate)


class Endpointer:
    """Turns a stream of PCM16 into turn boundaries.

    Hysteresis on both edges, because a single frame means nothing: a keyboard
    click reads as speech for one frame, and a stop consonant reads as silence
    for several. `start_ms` of speech opens a turn; `end_silence_ms` of silence
    closes it.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        frame_ms: int = 20,
        gate: SpeechGate | None = None,
        aggressiveness: int = 2,
        start_ms: int = 100,
        end_silence_ms: int = 700,
        preroll_ms: int = 300,
        max_turn_s: float = 120.0,
    ) -> None:
        if frame_ms not in (10, 20, 30):
            raise ValueError("webrtcvad accepts 10, 20 or 30 ms frames only")
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError("webrtcvad accepts 8, 16, 32 or 48 kHz only")

        self.sample_rate = sample_rate
        self._frame_bytes = int(sample_rate * frame_ms / 1000) * 2
        self._frame_ms = frame_ms
        self._gate = gate if gate is not None else WebrtcGate(aggressiveness)

        self._start_frames = max(1, round(start_ms / frame_ms))
        self._end_frames = max(1, round(end_silence_ms / frame_ms))
        self._max_turn_bytes = int(max_turn_s * sample_rate) * 2

        # Pre-roll: the frames immediately before the trigger. Without it the
        # turn audio starts `start_ms` late and Whisper never sees the first
        # consonant of the first word.
        self._preroll: collections.deque[bytes] = collections.deque(
            maxlen=max(1, round(preroll_ms / frame_ms))
        )

        self._carry = b""
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._turn = bytearray()
        self._taken = 0

    # ------------------------------------------------------------------

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def turn_bytes(self) -> int:
        return len(self._turn)

    def feed(self, pcm16: bytes) -> list[Boundary]:
        """Consume audio and return any boundaries it crossed.

        The browser sends ~80 ms chunks, which is not a whole number of VAD
        frames at every frame size, so leftovers carry to the next call.
        """
        self._carry += pcm16
        out: list[Boundary] = []
        while len(self._carry) >= self._frame_bytes:
            frame = self._carry[: self._frame_bytes]
            self._carry = self._carry[self._frame_bytes :]
            out.extend(self._feed_frame(frame))
        return out

    def _feed_frame(self, frame: bytes) -> list[Boundary]:
        speech = self._gate.is_speech(frame, self.sample_rate)

        if not self._in_speech:
            self._preroll.append(frame)
            self._speech_run = self._speech_run + 1 if speech else 0
            if self._speech_run < self._start_frames:
                return []
            self._in_speech = True
            self._silence_run = 0
            self._turn = bytearray(b"".join(self._preroll))
            self._taken = 0
            self._preroll.clear()
            return [Boundary(Decision.SPEECH_STARTED, b"", 0.0)]

        self._turn += frame
        self._silence_run = 0 if speech else self._silence_run + 1

        if len(self._turn) >= self._max_turn_bytes:
            # A candidate who has not paused in two minutes is monologuing, and
            # Whisper's upload ceiling is 25 MB. Cut the turn rather than
            # buffer until the request fails.
            return [self._close(forced=True)]

        if self._silence_run >= self._end_frames:
            return [self._close(forced=False)]

        return []

    def _close(self, *, forced: bool) -> Boundary:
        audio = bytes(self._turn)
        self._turn = bytearray()
        self._taken = 0
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._preroll.clear()
        return Boundary(
            Decision.SPEECH_ENDED,
            audio,
            len(audio) / 2 / self.sample_rate,
            forced=forced,
        )

    def take_increment(self) -> bytes:
        """Audio accumulated in the current turn since the last call.

        Used for interim transcripts. Returning only the *new* audio — rather
        than the whole turn so far — keeps each interim request small and keeps
        the audio-seconds bill linear in speech rather than quadratic in turn
        length. The cost is that interim text can split a word at a chunk
        boundary, which is acceptable because interim transcripts are only ever
        shown as a live caption: `session.py` forwards the UPDATE transcript to
        the browser as `transcript_partial` and makes no decision on it. The
        transcript it *acts* on comes from END_OF_TURN, which is transcribed
        from the whole turn in a single request.
        """
        if not self._in_speech:
            return b""
        taken = bytes(self._turn[self._taken :])
        self._taken = len(self._turn)
        return taken

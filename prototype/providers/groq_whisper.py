"""Groq Whisper + a local endpointer, worn as a streaming STT provider (ADR-009).

Endpoint: POST https://api.groq.com/openai/v1/audio/transcriptions
  https://console.groq.com/docs/speech-to-text

Whisper on Groq is a *batch* API: you post a file, you get a transcript. There
is no streaming endpoint and no turn detection. So this provider manufactures
both halves of what Deepgram Flux delivered natively, and the real content of
this file is the two decisions about how.

Decision 1 — how audio is chunked into transcription calls
----------------------------------------------------------
Not on a timer. The local VAD in `_endpointer.py` decides where turns begin and
end, and **a turn is the unit of transcription**. That matters because a
fixed-size window would cut mid-word and Whisper cannot carry context across
calls, whereas a turn boundary is by construction a point where nobody is
talking.

Per candidate turn:

* **one** request over the whole turn's audio, issued at the VAD's
  end-of-speech, whose result becomes `END_OF_TURN`. This is the transcript the
  orchestrator acts on, so it gets the single request with full context.
* zero or more small requests over *incremental* audio while the turn is still
  running, each becoming an `UPDATE`.

Decision 2 — how interim transcripts are produced at all
---------------------------------------------------------
This is the part with no clean answer. Flux emitted `Update` continuously for
free. Here every interim costs a request against a 20 RPM ceiling, shared with
the end-of-turn requests that actually matter.

Two options were considered:

* **Re-transcribe the whole turn so far, every N seconds.** Accurate — Whisper
  sees full context every time — but the audio-seconds bill grows with the
  square of turn length (a 20 s turn re-transcribed every 2 s is 110 s of
  audio), and a few long answers would exhaust the per-hour audio allowance.
* **Transcribe only the new audio since the last interim, and concatenate.**
  Linear in speech, each request small and fast. The cost is that a word
  straddling an interim boundary can come out wrong, with no cross-chunk
  context to fix it.

The second wins, for a reason specific to this codebase: **interim transcripts
are display-only.** `session.py` turns an `UPDATE` into a `transcript_partial`
message for the browser's live caption and makes no decision on its text — the
only candidate transcript reaching the interview state machine or the LLM comes
from `END_OF_TURN`. So a mangled word in a caption costs cosmetics, while the
transcript that matters is always one whole-turn request. If interims ever
become load-bearing, revisit this first.

Interims are additionally rate-limited (`_RequestBudget`) and *skipped*, never
queued, when the budget is tight: an interim that arrives late is worthless,
and starving the end-of-turn request to deliver one would be strictly worse.

What is given up versus Flux
-----------------------------
* `EAGER_END_OF_TURN` / `TURN_RESUMED` are never emitted. A VAD has no semantic
  signal to speculate from — see the module docstring in `_endpointer.py`. Per
  `SttProvider`'s contract the orchestrator degrades to non-speculative
  generation, which costs the full LLM time-to-first-token at end-of-turn
  instead of the ~250 ms head start measured in docs/LATENCY.md.
* `end_of_turn_confidence` is always 0.0 and `words` is always empty. Whisper's
  `verbose_json` can return segment timings, but nothing consumes them today
  and asking for them costs response size on the latency-critical path.

What is gained
--------------
* **`prompt` biasing works.** Flux accepts `keyterm` and silently ignores it
  (measured, docs/LATENCY.md) — the worst quality finding of the Deepgram
  validation, because the words it mangles are the technical terms the
  interview is *about*. Whisper's `prompt` demonstrably moves them: measured
  WER on a term-dense utterance went 0.438 -> 0.125. So this provider takes a
  `prompt` built from the role and the job description.
* **Silence is no longer billable.** COST_MODEL Note 1 records that Flux drives
  its silence timeout from received audio, so the client had to stream silence
  for the whole wall clock and STT billed all 30 minutes. Endpointing locally
  inverts that: only speech is ever uploaded, so audio-seconds track talking
  rather than sitting.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import AsyncIterator

from groq import AsyncGroq

from providers._audio import wrap_wav
from providers._endpointer import Boundary, Decision, Endpointer, SpeechGate
from providers.base import SttEvent, TurnEvent

log = logging.getLogger("intervueos.stt")


class _RequestBudget:
    """Sliding-window request counter for the per-minute ceiling.

    Not a throttle — nothing here ever waits. `allow()` answers "is there
    headroom right now", and interim transcription is skipped when the answer is
    no. `reserve` holds back a slice of the window for end-of-turn requests,
    which must never be starved by captions.
    """

    def __init__(self, per_minute: int, reserve: int) -> None:
        self._limit = per_minute
        self._reserve = reserve
        self._hits: collections.deque[float] = collections.deque()

    def _evict(self, now: float) -> None:
        while self._hits and now - self._hits[0] > 60.0:
            self._hits.popleft()

    def allow(self, *, privileged: bool) -> bool:
        now = time.monotonic()
        self._evict(now)
        ceiling = self._limit if privileged else self._limit - self._reserve
        return len(self._hits) < ceiling

    def charge(self) -> None:
        self._hits.append(time.monotonic())

    @property
    def used(self) -> int:
        self._evict(time.monotonic())
        return len(self._hits)


class GroqWhisperStt:
    """Satisfies `providers.base.SttProvider`.

    Constructor keywords mirror `DeepgramFluxStt` where they mean the same
    thing, so the two are interchangeable at the single construction site in
    `server.py`. Flux's confidence thresholds have no analogue here and are
    replaced by `end_silence_ms`.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "whisper-large-v3",
        sample_rate: int = 16000,
        language: str = "en",
        prompt: str = "",
        end_silence_ms: int = 700,
        start_ms: int = 100,
        preroll_ms: int = 300,
        vad_aggressiveness: int = 2,
        interim_interval_s: float = 4.0,
        min_interim_s: float = 1.0,
        requests_per_minute: int = 20,
        reserve_requests: int = 6,
        max_turn_s: float = 120.0,
        gate: SpeechGate | None = None,
        max_retries: int = 1,
        timeout: float = 20.0,
    ) -> None:
        self.sample_rate = sample_rate
        self._client = AsyncGroq(api_key=api_key, max_retries=max_retries, timeout=timeout)
        self._model = model
        self._language = language
        self._prompt = prompt[:800]  # Whisper caps `prompt` at 224 tokens.

        self._endpointer = Endpointer(
            sample_rate=sample_rate,
            gate=gate,
            aggressiveness=vad_aggressiveness,
            start_ms=start_ms,
            end_silence_ms=end_silence_ms,
            preroll_ms=preroll_ms,
            max_turn_s=max_turn_s,
        )
        self._budget = _RequestBudget(requests_per_minute, reserve_requests)
        self._interim_interval_s = interim_interval_s
        self._min_interim_bytes = int(min_interim_s * sample_rate) * 2

        self._events: asyncio.Queue[SttEvent | None] = asyncio.Queue()
        self._turn_index = 0
        self._interim_text: list[str] = []
        self._last_interim_at = 0.0
        self._interim_task: asyncio.Task | None = None
        self._closed = False

        self.metrics: dict[str, list[float]] = {
            "final_transcribe_ms": [],
            "interim_transcribe_ms": [],
            "speech_seconds": [],
            "interims_skipped": [],
        }

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "GroqWhisperStt":
        self._closed = False
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._closed = True
        await self._cancel_interim()
        await self._events.put(None)
        await self._client.close()

    # ------------------------------------------------------------------
    # SttProvider surface
    # ------------------------------------------------------------------

    async def send_audio(self, pcm16: bytes) -> None:
        """Feed raw little-endian PCM16 mono at `sample_rate`.

        Runs the VAD inline. It is microseconds per 20 ms frame, which is the
        whole point of `_endpointer.py` being synchronous — pushing it to a
        thread would add a hop to the most latency-sensitive path in the system
        in order to avoid work that does not exist.
        """
        if self._closed:
            return
        for boundary in self._endpointer.feed(pcm16):
            await self._on_boundary(boundary)

        if self._endpointer.in_speech:
            await self._maybe_interim()

    async def events(self) -> AsyncIterator[SttEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    # ------------------------------------------------------------------
    # turn boundaries
    # ------------------------------------------------------------------

    async def _on_boundary(self, boundary: Boundary) -> None:
        if boundary.decision is Decision.SPEECH_STARTED:
            self._turn_index += 1
            self._interim_text = []
            self._last_interim_at = time.monotonic()
            await self._events.put(
                SttEvent(
                    event=TurnEvent.START_OF_TURN,
                    transcript="",
                    turn_index=self._turn_index,
                )
            )
            return

        # SPEECH_ENDED. Stop any interim in flight: its text is about to be
        # superseded by the whole-turn transcript, and it is competing for the
        # same request budget.
        await self._cancel_interim()
        self.metrics["speech_seconds"].append(boundary.speech_s)

        text = ""
        if boundary.audio:
            started = time.monotonic()
            try:
                text = await self._transcribe(boundary.audio, privileged=True)
            except Exception:
                log.exception("whisper end-of-turn transcription failed")
            else:
                self.metrics["final_transcribe_ms"].append(
                    (time.monotonic() - started) * 1000
                )

        await self._events.put(
            SttEvent(
                event=TurnEvent.END_OF_TURN,
                transcript=text,
                turn_index=self._turn_index,
                trigger="max_turn" if boundary.forced else "vad_silence",
                audio_window_end=boundary.speech_s,
            )
        )

    # ------------------------------------------------------------------
    # interim transcripts
    # ------------------------------------------------------------------

    async def _maybe_interim(self) -> None:
        if self._interim_interval_s <= 0 or self._interim_task is not None:
            return
        if time.monotonic() - self._last_interim_at < self._interim_interval_s:
            return
        if self._endpointer.turn_bytes < self._min_interim_bytes:
            return
        if not self._budget.allow(privileged=False):
            # Captions yield to end-of-turn requests, silently.
            self.metrics["interims_skipped"].append(1.0)
            self._last_interim_at = time.monotonic()
            return

        chunk = self._endpointer.take_increment()
        self._last_interim_at = time.monotonic()
        if len(chunk) < self._min_interim_bytes:
            return
        self._interim_task = asyncio.create_task(
            self._run_interim(chunk, self._turn_index), name="whisper-interim"
        )

    async def _run_interim(self, chunk: bytes, turn_index: int) -> None:
        started = time.monotonic()
        try:
            text = await self._transcribe(chunk, privileged=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("whisper interim failed", exc_info=True)
            return
        finally:
            self._interim_task = None

        if turn_index != self._turn_index or not text:
            return
        self.metrics["interim_transcribe_ms"].append((time.monotonic() - started) * 1000)
        self._interim_text.append(text)
        await self._events.put(
            SttEvent(
                event=TurnEvent.UPDATE,
                transcript=" ".join(self._interim_text),
                turn_index=turn_index,
            )
        )

    async def _cancel_interim(self) -> None:
        task, self._interim_task = self._interim_task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------

    async def _transcribe(self, pcm16: bytes, *, privileged: bool) -> str:
        self._budget.charge()
        kwargs = {"prompt": self._prompt} if self._prompt else {}
        result = await self._client.audio.transcriptions.create(
            file=("turn.wav", wrap_wav(pcm16, self.sample_rate), "audio/wav"),
            model=self._model,
            language=self._language,
            temperature=0,
            response_format="json",
            **kwargs,
        )
        return (getattr(result, "text", "") or "").strip()

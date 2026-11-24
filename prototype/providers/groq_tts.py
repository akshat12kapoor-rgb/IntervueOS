"""Groq Orpheus — batch TTS worn as a streaming provider (ADR-009).

Endpoint: POST https://api.groq.com/openai/v1/audio/speech
  https://console.groq.com/docs/text-to-speech

Three documented properties of Orpheus shape this whole file, and all three are
worse than Aura-2's:

1. **No streaming.** The response is one complete WAV body. Aura-2 streams audio
   frames as it synthesises, so its time-to-first-byte barely moves with
   utterance length. Here, time-to-first-byte *is* the full synthesis time of
   the first piece — which is why `speak()` synthesises each sentence the moment
   it arrives instead of waiting for `flush()`.

2. **`input` caps at 200 characters.** Shorter than a long interviewer sentence,
   so splitting is on the hot path, not a guard. See
   `_audio.split_for_synthesis`.

3. **10 requests/minute, 100 requests/day.** This is the binding constraint on
   the whole free-tier pipeline — see docs/COST_MODEL.md. Deliberately *not*
   rate-limited client-side: respecting 10 RPM means a six-second wait before
   speaking, and an interviewer that pauses six seconds is worse than one that
   errors. We let the 429 surface and account for it in the cost model instead.

The one thing that is *better* than Aura-2: barge-in is exact. Aura-2 keeps
sending ~0.92 s of already-synthesised speech after `Clear` (measured, see
docs/LATENCY.md), so `deepgram_aura.py` needs a local drop flag to avoid
speaking the tail of an interrupted question. Here nothing is in flight that we
do not hold ourselves, so `clear()` is immediate by construction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from groq import AsyncGroq

from providers._audio import split_for_synthesis, unwrap_wav

log = logging.getLogger("intervueos.tts")

MAX_INPUT_CHARS = 200
"""Orpheus's documented `input` ceiling."""


class GroqOrpheusTts:
    """Satisfies `providers.base.TtsProvider`.

    Constructor keywords mirror `DeepgramAuraTts` so the two are interchangeable
    at the single construction site in `server.py`.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "canopylabs/orpheus-v1-english",
        voice: str = "autumn",
        sample_rate: int = 24000,
        chunk_ms: int = 40,
        max_retries: int = 1,
        timeout: float = 20.0,
    ) -> None:
        self.sample_rate = sample_rate
        self._client = AsyncGroq(api_key=api_key, max_retries=max_retries, timeout=timeout)
        self._model = model
        self._voice = voice
        self._chunk_bytes = max(2, int(sample_rate * chunk_ms / 1000) * 2)

        self._pending: asyncio.Queue[str | None] = asyncio.Queue()
        self._out: asyncio.Queue[bytes] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

        # Barge-in uses an epoch rather than a drop flag: `clear()` bumps it,
        # and audio produced under a stale epoch is discarded at the boundary
        # between synthesis and output. A plain flag would race with a request
        # that is already in flight.
        self._epoch = 0

        self.metrics: dict[str, list[float]] = {"ttfb_ms": [], "synth_ms": []}
        self._utterance_started: float | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "GroqOrpheusTts":
        self._worker = asyncio.create_task(self._run(), name="orpheus-worker")
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stop_worker()
        await self._client.close()

    async def _stop_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None and not worker.done():
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------
    # TtsProvider surface
    # ------------------------------------------------------------------

    async def speak(self, text: str) -> None:
        """Queue text for synthesis.

        Enqueues eagerly — synthesis starts as soon as the worker is free rather
        than at `flush()`. With no streaming from the vendor, overlapping the
        synthesis of piece N+1 with the playback of piece N is the only thing
        standing between us and a gap in the middle of every sentence.
        """
        text = text.strip()
        if not text:
            return
        if self._utterance_started is None:
            self._utterance_started = time.monotonic()
        for piece in split_for_synthesis(text, MAX_INPUT_CHARS):
            await self._pending.put(piece)

    async def flush(self) -> None:
        """End of utterance.

        Nothing to force: `speak()` already queued everything. This only marks
        the boundary so the next utterance measures its own
        time-to-first-byte.
        """
        await self._pending.put(None)

    async def clear(self) -> None:
        """Barge-in. Drop queued text, cancel the request in flight, drop audio."""
        self._epoch += 1
        self._utterance_started = None
        _drain(self._pending)
        _drain(self._out)
        # Restarting the worker is what cancels an in-flight HTTP request; there
        # is no vendor-side "stop" to send.
        running = self._worker is not None
        await self._stop_worker()
        if running:
            self._worker = asyncio.create_task(self._run(), name="orpheus-worker")

    async def audio(self) -> AsyncIterator[bytes]:
        while True:
            yield await self._out.get()

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            piece = await self._pending.get()
            if piece is None:
                self._utterance_started = None
                continue
            epoch = self._epoch
            try:
                pcm = await self._synthesise(piece)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("orpheus synthesis failed for %r", piece[:60])
                continue
            if epoch != self._epoch:
                # Interrupted while this request was in flight. Throwing the
                # audio away here is what makes barge-in exact.
                continue
            for i in range(0, len(pcm), self._chunk_bytes):
                await self._out.put(pcm[i : i + self._chunk_bytes])

    async def _synthesise(self, text: str) -> bytes:
        started = time.monotonic()
        response = await self._client.audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
            response_format="wav",
        )
        body = await response.read()
        elapsed = (time.monotonic() - started) * 1000
        self.metrics["synth_ms"].append(elapsed)
        if self._utterance_started is not None:
            self.metrics["ttfb_ms"].append(
                (time.monotonic() - self._utterance_started) * 1000
            )
            self._utterance_started = None
        log.debug("orpheus %d chars in %d ms", len(text), round(elapsed))
        return unwrap_wav(body, self.sample_rate)


def _drain(queue: asyncio.Queue) -> None:
    while not queue.empty():
        queue.get_nowait()

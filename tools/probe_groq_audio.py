"""Live Groq audio validation (ADR-009).

Real API calls through the real provider classes. No mocks — the point is to
measure what `server.py` would actually run, not a reimplementation of it.

Audio is streamed into `GroqWhisperStt` at 80 ms per chunk, exactly as the
browser does, so the VAD sees the same frame cadence and the end-of-turn lag is
a real measurement of the shipped endpointer. What it is *not* is a measurement
of a human in a room: the input is a clean recording, so the VAD has an easy
job and every number here is a best case — the same caveat docs/LATENCY.md
carries for the Deepgram figures.

    .venv/bin/python tools/probe_groq_audio.py <16k-mono.wav>

Generate an input on macOS with:

    say -v Samantha -o raw.aiff "..."
    afconvert -f WAVE -d LEI16@16000 -c 1 raw.aiff in.wav
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import statistics
import sys
import time
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "prototype"))

from config import CONFIG  # noqa: E402
from providers.base import TurnEvent  # noqa: E402
from providers.groq_tts import GroqOrpheusTts  # noqa: E402
from providers.groq_whisper import GroqWhisperStt  # noqa: E402

CHUNK_MS = 80
TERM_HINT = (
    "A technical interview for a Senior Backend Engineer role. "
    "Topics: system design, databases, failure modes. "
    "Context: Postgres, PgBouncer, Redis, sharding, p99 latency, Kafka, "
    "idempotency, payments service, ledger."
)


def read_pcm(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise SystemExit(
                f"{path}: need 16 kHz mono PCM16, got {w.getframerate()} Hz "
                f"{w.getnchannels()}ch {w.getsampwidth() * 8}-bit"
            )
        return w.readframes(w.getnframes())


def median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


# ----------------------------------------------------------------------
# STT: end-of-turn lag, the number that replaces Flux's 1295 ms
# ----------------------------------------------------------------------


async def probe_stt(pcm: bytes, *, prompt: str, model: str) -> dict:
    """Stream audio in real time and time the end-of-turn.

    `eot_lag_ms` is measured from the moment the last chunk containing speech
    was sent to the moment END_OF_TURN was yielded. That is the quantity
    directly comparable to Flux's measured EOT lag: it includes the VAD's
    silence wait *and* the Whisper round trip, because the candidate
    experiences both as a single silence.
    """
    chunk = int(16000 * CHUNK_MS / 1000) * 2
    stt = GroqWhisperStt(
        api_key=CONFIG.groq_api_key,
        model=model,
        sample_rate=16000,
        prompt=prompt,
        end_silence_ms=CONFIG.vad_end_silence_ms,
        start_ms=CONFIG.vad_start_ms,
        preroll_ms=CONFIG.vad_preroll_ms,
        vad_aggressiveness=CONFIG.vad_aggressiveness,
        interim_interval_s=CONFIG.stt_interim_interval_s,
    )

    events: list[tuple[float, object]] = []
    # Tail of silence: the endpointer has to *hear* the pause to declare the
    # turn over. Unlike Flux this is a local decision, so the silence costs no
    # request and no audio-seconds — but it still has to arrive.
    tail = b"\x00\x00" * int(16000 * 1.5)

    async with stt:

        async def pump():
            async for ev in stt.events():
                events.append((time.monotonic(), ev))

        reader = asyncio.create_task(pump())
        started = time.monotonic()

        for i in range(0, len(pcm), chunk):
            await stt.send_audio(pcm[i : i + chunk])
            await asyncio.sleep(CHUNK_MS / 1000)
        speech_end_at = time.monotonic()

        for i in range(0, len(tail), chunk):
            await stt.send_audio(tail[i : i + chunk])
            await asyncio.sleep(CHUNK_MS / 1000)

        await asyncio.sleep(1.0)
        reader.cancel()

    finals = [(t, e) for t, e in events if e.event is TurnEvent.END_OF_TURN]
    updates = [e for _, e in events if e.event is TurnEvent.UPDATE]
    return {
        "model": model,
        "prompt": bool(prompt),
        "audio_s": round(len(pcm) / 2 / 16000, 2),
        "turns_detected": len(finals),
        "eot_lag_ms": round((finals[0][0] - speech_end_at) * 1000) if finals else None,
        "whisper_final_ms": median(stt.metrics["final_transcribe_ms"]),
        "interims": len(updates),
        "interims_skipped": len(stt.metrics["interims_skipped"]),
        "speech_s_billed": round(sum(stt.metrics["speech_seconds"]), 2),
        "wall_s": round(speech_end_at - started, 2),
        "transcript": finals[0][1].transcript if finals else "",
    }


# ----------------------------------------------------------------------
# TTS: time to first audio byte, against Aura-2's measured 334 ms
# ----------------------------------------------------------------------


async def probe_tts(text: str) -> dict:
    tts = GroqOrpheusTts(
        api_key=CONFIG.groq_api_key,
        model=CONFIG.groq_tts_model,
        voice=CONFIG.groq_tts_voice,
        sample_rate=CONFIG.tts_sample_rate,
    )
    first_at: float | None = None
    total = 0

    async with tts:

        async def pump():
            nonlocal first_at, total
            async for buf in tts.audio():
                if first_at is None:
                    first_at = time.monotonic()
                total += len(buf)

        reader = asyncio.create_task(pump())
        started = time.monotonic()
        await tts.speak(text)
        await tts.flush()
        await asyncio.sleep(12.0)
        reader.cancel()

    return {
        "model": CONFIG.groq_tts_model,
        "voice": CONFIG.groq_tts_voice,
        "chars": len(text),
        "ttfb_ms": round((first_at - started) * 1000) if first_at else None,
        "synth_ms_per_request": [round(x) for x in tts.metrics["synth_ms"]],
        "audio_bytes": total,
        "audio_s": round(total / 2 / CONFIG.tts_sample_rate, 2),
    }


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    pcm = read_pcm(sys.argv[1])

    print("--- STT: Groq Whisper + local VAD ---")
    for model in ("whisper-large-v3", "whisper-large-v3-turbo"):
        for prompt in (TERM_HINT, ""):
            print(json.dumps(await probe_stt(pcm, prompt=prompt, model=model)))
            await asyncio.sleep(2.0)  # 20 RPM ceiling

    print("--- TTS: Groq Orpheus ---")
    try:
        print(
            json.dumps(
                await probe_tts(
                    "So you sharded the ledger table. What did you measure to "
                    "land on two thousand writes a second as the breaking point?"
                )
            )
        )
    except Exception as exc:
        print(json.dumps({"tts_error": f"{type(exc).__name__}: {exc}"[:300]}))


if __name__ == "__main__":
    asyncio.run(main())

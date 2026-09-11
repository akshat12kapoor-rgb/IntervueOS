"""Live Deepgram validation.

Real API calls, real audio, real turn detection. No mocks.

The candidate's voice is synthesised with Deepgram Aura (a different voice from
the interviewer) and streamed into Flux in real time at 80 ms per chunk, exactly
as the browser does. That makes the STT, end-of-turn and latency numbers real
measurements of the provider path.

It does NOT make them measurements of a human speaking. Synthetic speech has
clean articulation, no background noise, and only the disfluencies we write into
it. Treat every number here as a best case.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import statistics
import struct
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "prototype"))

from websockets.asyncio.client import connect

from config import CONFIG
from providers._tls import tls_context
from providers.base import TurnEvent
from providers.deepgram_flux import DeepgramFluxStt

ART = pathlib.Path(__file__).resolve().parent.parent / "artifacts"
ART.mkdir(exist_ok=True)

CANDIDATE_VOICE = "aura-2-orion-en"     # candidate
INTERVIEWER_VOICE = CONFIG.tts_model    # interviewer
RATE = 16000


# ---------------------------------------------------------------- synthesis

async def synth(text: str, voice: str, rate: int = RATE) -> tuple[bytes, float]:
    """One-shot synthesis. Returns (pcm16, time_to_first_byte_ms) including
    connection setup — used for building candidate audio, not for latency
    claims."""
    url = "wss://api.deepgram.com/v1/speak?" + urlencode(
        {"model": voice, "encoding": "linear16", "sample_rate": str(rate)}
    )
    out = bytearray()
    t0 = time.monotonic()
    ttfb = None
    async with connect(
        url,
        additional_headers={"Authorization": f"Token {CONFIG.deepgram_api_key}"},
        ssl=tls_context(),
        max_size=None,
    ) as ws:
        await ws.send(json.dumps({"type": "Speak", "text": text}))
        await ws.send(json.dumps({"type": "Flush"}))
        async for raw in ws:
            if isinstance(raw, bytes):
                if ttfb is None:
                    ttfb = (time.monotonic() - t0) * 1000
                out.extend(raw)
            else:
                if json.loads(raw).get("type") == "Flushed":
                    break
    return bytes(out), ttfb or 0.0


def wav(path: pathlib.Path, pcm: bytes, rate: int = RATE) -> None:
    hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16
    ) + b"data" + struct.pack("<I", len(pcm))
    path.write_bytes(hdr + pcm)


# ------------------------------------------------- probe A: TTS steady state

async def probe_tts_steady_state(utterances: list[str]) -> dict:
    """TTFB on an ALREADY-OPEN socket, which is the case during an interview.
    Measuring a fresh connection each time inflates this by the TLS handshake."""
    url = "wss://api.deepgram.com/v1/speak?" + urlencode(
        {"model": INTERVIEWER_VOICE, "encoding": "linear16", "sample_rate": "24000"}
    )
    first_call, steady, chars = [], [], []
    async with connect(
        url,
        additional_headers={"Authorization": f"Token {CONFIG.deepgram_api_key}"},
        ssl=tls_context(),
        max_size=None,
    ) as ws:
        for i, text in enumerate(utterances):
            t0 = time.monotonic()
            await ws.send(json.dumps({"type": "Speak", "text": text}))
            await ws.send(json.dumps({"type": "Flush"}))
            ttfb = None
            async for raw in ws:
                if isinstance(raw, bytes):
                    if ttfb is None:
                        ttfb = (time.monotonic() - t0) * 1000
                elif json.loads(raw).get("type") == "Flushed":
                    break
            (first_call if i == 0 else steady).append(ttfb)
            chars.append(len(text))
    return {
        "first_utterance_on_new_socket_ms": round(first_call[0]) if first_call else None,
        "steady_state_ttfb_ms": {
            "n": len(steady),
            "median": round(statistics.median(steady)),
            "min": round(min(steady)),
            "max": round(max(steady)),
        },
        "mean_chars": round(statistics.mean(chars)),
    }


# --------------------------------------------------- probe B: STT / turn model

async def stream_utterance(
    stt: DeepgramFluxStt, pcm: bytes, *, done: asyncio.Event, max_silence_s: float = 10.0
) -> float:
    """Feed audio at wall-clock speed, then keep feeding silence until the turn
    ends. Flux's silence timeout is driven by received audio, so a probe that
    simply stops sending never gets an EndOfTurn at all."""
    chunk = int(RATE * 0.08) * 2
    for i in range(0, len(pcm), chunk):
        await stt.send_audio(pcm[i : i + chunk])
        await asyncio.sleep(0.08)
    audio_end = time.monotonic()

    silent_chunk = b"\x00\x00" * int(RATE * 0.08)
    deadline = audio_end + max_silence_s
    while not done.is_set() and time.monotonic() < deadline:
        await stt.send_audio(silent_chunk)
        await asyncio.sleep(0.08)
    return audio_end


def wer(ref: str, hyp: str) -> float:
    import re
    r = re.sub(r"[^a-z0-9 ]", "", ref.lower()).split()
    h = re.sub(r"[^a-z0-9 ]", "", hyp.lower()).split()
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + (r[i - 1] != h[j - 1]),
            )
    return d[len(r)][len(h)] / max(1, len(r))


async def probe_stt(cases: list[dict]) -> dict:
    results = []
    async with DeepgramFluxStt(
        api_key=CONFIG.deepgram_api_key,
        model=CONFIG.stt_model,
        sample_rate=RATE,
        eot_threshold=CONFIG.eot_threshold,
        eager_eot_threshold=CONFIG.eager_eot_threshold,
        eot_timeout_ms=CONFIG.eot_timeout_ms,
    ) as stt:
        events: list[tuple[float, object]] = []
        done = asyncio.Event()

        async def collect():
            async for ev in stt.events():
                events.append((time.monotonic(), ev))
                if ev.event is TurnEvent.END_OF_TURN:
                    done.set()

        pump = asyncio.create_task(collect())

        for case in cases:
            pcm, _ = await synth(case["text"], CANDIDATE_VOICE)
            audio_s = len(pcm) / 2 / RATE
            events.clear()
            done.clear()
            audio_end = await stream_utterance(stt, pcm, done=done)

            eots = [(t, e) for t, e in events if e.event is TurnEvent.END_OF_TURN]
            eagers = [(t, e) for t, e in events if e.event is TurnEvent.EAGER_END_OF_TURN]
            resumed = [(t, e) for t, e in events if e.event is TurnEvent.TURN_RESUMED]
            final = eots[0][1].transcript if eots else ""
            results.append({
                "label": case["label"],
                "audio_s": round(audio_s, 2),
                "reference": case["text"],
                "transcript": final,
                "wer": round(wer(case["text"], final), 3),
                "eot_count": len(eots),
                "eot_after_audio_end_ms": round((eots[0][0] - audio_end) * 1000) if eots else None,
                "eager_count": len(eagers),
                "turn_resumed_count": len(resumed),
                "eager_lead_ms": (
                    round((eots[0][0] - eagers[0][0]) * 1000) if eots and eagers else None
                ),
                "eager_transcript_matched_final": (
                    bool(eagers) and bool(eots)
                    and eagers[-1][1].transcript.strip().lower().rstrip(".")
                    == final.strip().lower().rstrip(".")
                ),
                "eot_confidence": round(eots[0][1].end_of_turn_confidence, 3) if eots else None,
                "eot_trigger": eots[0][1].trigger if eots else None,
            })
            await asyncio.sleep(0.4)

        pump.cancel()
    return {"cases": results}


# ------------------------------------------------------------------- runner

CASES = [
    {"label": "fluent_technical", "text":
     "I built the payments service on Postgres with an outbox table, and we published "
     "events to Kafka from a separate relay process so the write and the publish "
     "shared a transaction."},
    {"label": "hesitant_with_pauses", "text":
     "So, um, the tricky part was... idempotency. We had a, a dedupe key on the "
     "consumer side, and, uh, we stored it in Redis with a twenty four hour TTL."},
    {"label": "short_answer", "text": "About four hundred requests per second at peak."},
    {"label": "mid_sentence_pause", "text":
     "The main tradeoff was between consistency and latency, and... honestly we "
     "chose latency because the product team wanted sub two hundred millisecond writes."},
    {"label": "numbers_and_jargon", "text":
     "We sharded by tenant ID across sixteen Postgres instances, ran PgBouncer in "
     "transaction mode, and kept p99 under one hundred and twenty milliseconds."},
]

TTS_UTTERANCES = [
    "Walk me through how you would design a rate limiter.",
    "Why Redis rather than a relational database there?",
    "What happens when that node becomes unavailable?",
    "You said the team handled it. What did you do specifically?",
    "Earlier you said writes were synchronous. How does that fit with what you just described?",
    "What was the hardest tradeoff in that design?",
]


async def main() -> None:
    report: dict = {"config": {
        "stt_model": CONFIG.stt_model,
        "tts_model": CONFIG.tts_model,
        "eot_threshold": CONFIG.eot_threshold,
        "eager_eot_threshold": CONFIG.eager_eot_threshold,
        "eot_timeout_ms": CONFIG.eot_timeout_ms,
    }}

    print("probe A: TTS steady-state latency ...", flush=True)
    report["tts"] = await probe_tts_steady_state(TTS_UTTERANCES)
    print(json.dumps(report["tts"], indent=2), flush=True)

    print("\nprobe B: STT + turn detection (real audio) ...", flush=True)
    report["stt"] = await probe_stt(CASES)
    for c in report["stt"]["cases"]:
        print(f"  {c['label']:22} wer={c['wer']:.3f} eot={c['eot_count']} "
              f"eot_lag={c['eot_after_audio_end_ms']}ms eager={c['eager_count']} "
              f"resumed={c['turn_resumed_count']} match={c['eager_transcript_matched_final']}",
              flush=True)

    (ART / "voice_probe.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {ART / 'voice_probe.json'}")


if __name__ == "__main__":
    asyncio.run(main())

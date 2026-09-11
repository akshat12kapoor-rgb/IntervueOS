"""Probe C: does keyterm biasing fix the domain-vocabulary errors?
   Probe D: how fast does a real barge-in actually silence the vendor?"""

from __future__ import annotations

import asyncio, json, pathlib, statistics, sys, time
from urllib.parse import urlencode

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "prototype"))
from websockets.asyncio.client import connect

from config import CONFIG
from providers._tls import tls_context
from providers.base import TurnEvent
from providers.deepgram_aura import DeepgramAuraTts
from providers.deepgram_flux import DeepgramFluxStt
from voice_probe import CANDIDATE_VOICE, RATE, synth, wer

ART = pathlib.Path(__file__).resolve().parent.parent / "artifacts"

# The terms the baseline run actually got wrong, plus the rest of the stack a
# backend JD would mention. In production this list is derived from the JD and
# resume, which is exactly the material we already extract.
KEYTERMS = [
    "Redis", "PgBouncer", "Postgres", "sharded", "Kafka", "idempotency",
    "p99", "outbox", "dedupe", "TTL", "tenant",
]

CASES = [
    {"label": "numbers_and_jargon", "text":
     "We sharded by tenant ID across sixteen Postgres instances, ran PgBouncer in "
     "transaction mode, and kept p99 under one hundred and twenty milliseconds."},
    {"label": "hesitant_with_pauses", "text":
     "So, um, the tricky part was... idempotency. We had a, a dedupe key on the "
     "consumer side, and, uh, we stored it in Redis with a twenty four hour TTL."},
    {"label": "fluent_technical", "text":
     "I built the payments service on Postgres with an outbox table, and we published "
     "events to Kafka from a separate relay process so the write and the publish "
     "shared a transaction."},
]


def flux_url(keyterms: list[str] | None) -> str:
    params = [
        ("model", CONFIG.stt_model), ("encoding", "linear16"),
        ("sample_rate", str(RATE)), ("eot_threshold", str(CONFIG.eot_threshold)),
        ("eager_eot_threshold", str(CONFIG.eager_eot_threshold)),
        ("eot_timeout_ms", str(CONFIG.eot_timeout_ms)),
    ]
    for k in keyterms or []:
        params.append(("keyterm", k))
    return "wss://api.deepgram.com/v2/listen?" + urlencode(params)


async def run_cases(keyterms: list[str] | None, audio: dict) -> dict:
    url = flux_url(keyterms)
    results = {}
    try:
        ws = await connect(
            url,
            additional_headers={"Authorization": f"Token {CONFIG.deepgram_api_key}"},
            ssl=tls_context(), max_size=None,
        )
    except Exception as e:
        return {"connect_error": f"{type(e).__name__}: {e}"}

    async with ws:
        for case in CASES:
            pcm = audio[case["label"]]
            done = asyncio.Event()
            final = {"text": "", "trigger": None, "lags": None}
            t_end = [0.0]

            async def collect():
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    m = json.loads(raw)
                    if m.get("type") == "Error":
                        final["text"] = f"__ERROR__ {m}"
                        done.set(); return
                    if m.get("type") != "TurnInfo":
                        continue
                    if m.get("event") == "EndOfTurn":
                        final["text"] = m.get("transcript", "")
                        final["trigger"] = m.get("trigger")
                        final["lags"] = round((time.monotonic() - t_end[0]) * 1000)
                        done.set(); return

            pump = asyncio.create_task(collect())
            chunk = int(RATE * 0.08) * 2
            for i in range(0, len(pcm), chunk):
                await ws.send(pcm[i:i+chunk]); await asyncio.sleep(0.08)
            t_end[0] = time.monotonic()
            sil = b"\x00\x00" * int(RATE * 0.08)
            deadline = time.monotonic() + 10
            while not done.is_set() and time.monotonic() < deadline:
                await ws.send(sil); await asyncio.sleep(0.08)
            await asyncio.wait_for(done.wait(), timeout=3) if not done.is_set() else None
            pump.cancel()
            results[case["label"]] = {
                "transcript": final["text"],
                "wer": round(wer(case["text"], final["text"]), 3),
                "eot_lag_ms": final["lags"],
                "trigger": final["trigger"],
            }
            await asyncio.sleep(0.3)
    return results


async def probe_bargein(n: int = 5) -> dict:
    """Time from tts.clear() to the vendor's audio stream actually going quiet."""
    lat, leaked = [], []
    async with DeepgramAuraTts(
        api_key=CONFIG.deepgram_api_key, model=CONFIG.tts_model, sample_rate=24000
    ) as tts:
        state = {"last": 0.0, "bytes": 0, "clear_at": None}

        async def drain():
            async for chunk in tts.audio():
                state["last"] = time.monotonic()
                state["bytes"] += len(chunk)
                if state["clear_at"] is not None:
                    leaked.append(len(chunk))

        pump = asyncio.create_task(drain())
        for _ in range(n):
            state.update(last=0.0, bytes=0, clear_at=None)
            leaked.clear()
            await tts.speak(
                "Let me push on that a little. You said the write and the publish "
                "shared a transaction, so walk me through what happens when the relay "
                "process dies after the commit but before the publish."
            )
            await tts.flush()
            # Let real audio start flowing, then interrupt mid-utterance.
            while state["bytes"] == 0:
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.6)
            t_clear = time.monotonic()
            state["clear_at"] = t_clear
            await tts.clear()
            await asyncio.sleep(1.2)
            quiet_at = state["last"]
            lat.append(max(0.0, (quiet_at - t_clear) * 1000))
            await asyncio.sleep(0.3)
        pump.cancel()
    return {
        "n": n,
        "vendor_silence_after_clear_ms": {
            "median": round(statistics.median(lat)), "min": round(min(lat)), "max": round(max(lat))
        },
        "note": "time from Clear to the last audio byte the vendor sent; bytes after "
                "Clear are dropped client-side by the provider's _dropping flag",
    }


async def main() -> None:
    print("synthesising candidate audio once, reused for both arms ...", flush=True)
    audio = {}
    for c in CASES:
        pcm, _ = await synth(c["text"], CANDIDATE_VOICE)
        audio[c["label"]] = pcm

    print("\nprobe C: keyterm A/B", flush=True)
    base = await run_cases(None, audio)
    keyed = await run_cases(KEYTERMS, audio)
    report = {"baseline": base, "with_keyterms": keyed, "keyterms": KEYTERMS}

    if "connect_error" in keyed:
        print("  keyterm param REJECTED:", keyed["connect_error"])
    else:
        print(f"  {'case':22} {'wer base':>9} {'wer keyed':>10}")
        for label in base:
            if isinstance(base[label], dict):
                print(f"  {label:22} {base[label]['wer']:>9.3f} {keyed[label]['wer']:>10.3f}")

    print("\nprobe D: barge-in against the real vendor", flush=True)
    report["bargein"] = await probe_bargein()
    print(" ", json.dumps(report["bargein"]["vendor_silence_after_clear_ms"]))

    (ART / "probe2.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {ART/'probe2.json'}")


if __name__ == "__main__":
    asyncio.run(main())

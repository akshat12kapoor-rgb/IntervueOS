"""Sweep eot_threshold / eager_eot_threshold.

The end-of-turn lag is the single largest latency term in the loop, and it is a
config value. The risk of lowering it is cutting the candidate off mid-thought,
so the sweep measures both: how fast the turn ends, and how often it ends early.
"""

from __future__ import annotations

import asyncio, json, pathlib, statistics, sys, time
from urllib.parse import urlencode

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "prototype"))
from websockets.asyncio.client import connect

from config import CONFIG
from providers._tls import tls_context
from voice_probe import CANDIDATE_VOICE, RATE, synth, wer

ART = pathlib.Path(__file__).resolve().parent.parent / "artifacts"

CASES = [
    {"label": "fluent", "text":
     "I built the payments service on Postgres with an outbox table, and we published "
     "events to Kafka from a separate relay process so the write and the publish shared "
     "a transaction."},
    {"label": "hesitant", "text":
     "So, um, the tricky part was... idempotency. We had a, a dedupe key on the consumer "
     "side, and, uh, we stored it in Redis with a twenty four hour TTL."},
    {"label": "pauses_midway", "text":
     "The main tradeoff was between consistency and latency, and... honestly we chose "
     "latency because the product team wanted sub two hundred millisecond writes."},
]

GRID = [(0.7, 0.5), (0.6, 0.4), (0.5, 0.3), (0.5, 0.0)]


async def one(eot: float, eager: float, audio: dict) -> dict:
    params = [("model", CONFIG.stt_model), ("encoding", "linear16"),
              ("sample_rate", str(RATE)), ("eot_threshold", str(eot)),
              ("eot_timeout_ms", str(CONFIG.eot_timeout_ms))]
    if eager:
        params.append(("eager_eot_threshold", str(eager)))
    url = "wss://api.deepgram.com/v2/listen?" + urlencode(params)

    rows = []
    async with connect(
        url, additional_headers={"Authorization": f"Token {CONFIG.deepgram_api_key}"},
        ssl=tls_context(), max_size=None,
    ) as ws:
        for case in CASES:
            pcm = audio[case["label"]]
            audio_s = len(pcm) / 2 / RATE
            done = asyncio.Event()
            eots, eagers = [], []
            t_end = [None]

            async def collect():
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    m = json.loads(raw)
                    if m.get("type") != "TurnInfo":
                        continue
                    now = time.monotonic()
                    if m.get("event") == "EagerEndOfTurn":
                        eagers.append((now, m.get("transcript", "")))
                    elif m.get("event") == "EndOfTurn":
                        eots.append((now, m))
                        done.set(); return

            pump = asyncio.create_task(collect())
            chunk = int(RATE * 0.08) * 2
            t0 = time.monotonic()
            for i in range(0, len(pcm), chunk):
                if done.is_set():
                    break                       # turn ended while still speaking
                await ws.send(pcm[i:i+chunk]); await asyncio.sleep(0.08)
            t_end[0] = time.monotonic()
            spoken_s = t_end[0] - t0
            sil = b"\x00\x00" * int(RATE * 0.08)
            dl = time.monotonic() + 8
            while not done.is_set() and time.monotonic() < dl:
                await ws.send(sil); await asyncio.sleep(0.08)
            pump.cancel()

            if eots:
                t_eot, m = eots[0]
                premature = spoken_s < audio_s - 0.25
                last_eager = eagers[-1][0] if eagers else None
                rows.append({
                    "case": case["label"],
                    "eot_lag_ms": round((t_eot - t_end[0]) * 1000) if not premature else 0,
                    "premature": premature,
                    "wer": round(wer(case["text"], m.get("transcript", "")), 3),
                    "trigger": m.get("trigger"),
                    "eager_lead_ms": round((t_eot - last_eager) * 1000) if last_eager else None,
                    "eager_matched": (
                        bool(eagers)
                        and eagers[-1][1].strip().lower().rstrip(".")
                        == m.get("transcript", "").strip().lower().rstrip(".")
                    ),
                })
            else:
                rows.append({"case": case["label"], "eot_lag_ms": None, "premature": None})
            await asyncio.sleep(0.3)
    return {"eot_threshold": eot, "eager_eot_threshold": eager, "rows": rows}


async def main() -> None:
    audio = {}
    for c in CASES:
        pcm, _ = await synth(c["text"], CANDIDATE_VOICE)
        audio[c["label"]] = pcm

    out = []
    print(f"{'eot':>5} {'eager':>6} {'med lag':>9} {'premature':>10} {'mean wer':>9} {'eager lead':>11} {'match':>6}")
    print("-" * 66)
    for eot, eager in GRID:
        r = await one(eot, eager, audio)
        out.append(r)
        lags = [x["eot_lag_ms"] for x in r["rows"] if x["eot_lag_ms"] is not None]
        prem = sum(1 for x in r["rows"] if x.get("premature"))
        wers = [x["wer"] for x in r["rows"] if "wer" in x]
        leads = [x["eager_lead_ms"] for x in r["rows"] if x.get("eager_lead_ms")]
        match = sum(1 for x in r["rows"] if x.get("eager_matched"))
        print(f"{eot:>5} {eager:>6} {statistics.median(lags) if lags else '-':>9.0f} "
              f"{prem:>6}/{len(r['rows'])} {statistics.mean(wers) if wers else 0:>9.3f} "
              f"{statistics.median(leads) if leads else 0:>10.0f}ms {match:>4}/{len(r['rows'])}")

    (ART / "thresholds.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {ART/'thresholds.json'}")


if __name__ == "__main__":
    asyncio.run(main())

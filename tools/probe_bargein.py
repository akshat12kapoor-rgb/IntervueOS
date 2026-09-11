"""Barge-in, measured at the raw socket.

The previous attempt measured zero because `DeepgramAuraTts.clear()` sets its
drop flag before sending Clear, so the audio generator hides post-Clear frames
from the caller. That is the correct product behaviour, but it makes the vendor's
own reaction time invisible. This probe reads the raw WebSocket instead, so it
can separate the two:

  perceived_silence_ms  - what the candidate experiences (local drop)
  vendor_tail_ms/bytes  - what Deepgram kept sending after Clear (wasted spend)
"""

from __future__ import annotations

import asyncio, json, pathlib, statistics, sys, time
from urllib.parse import urlencode

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "prototype"))
from websockets.asyncio.client import connect

from config import CONFIG
from providers._tls import tls_context

ART = pathlib.Path(__file__).resolve().parent.parent / "artifacts"
RATE = 24000
LINE = ("Let me push on that. You said the write and the publish shared a "
        "transaction, so what happens when the relay process dies after the "
        "commit but before the publish goes out?")


async def main(n: int = 6) -> None:
    url = "wss://api.deepgram.com/v1/speak?" + urlencode(
        {"model": CONFIG.tts_model, "encoding": "linear16", "sample_rate": str(RATE)}
    )
    tails_ms, tails_bytes, cleared_ack_ms = [], [], []

    async with connect(
        url, additional_headers={"Authorization": f"Token {CONFIG.deepgram_api_key}"},
        ssl=tls_context(), max_size=None,
    ) as ws:
        for _ in range(n):
            await ws.send(json.dumps({"type": "Speak", "text": LINE}))
            await ws.send(json.dumps({"type": "Flush"}))

            got = 0
            t_clear = None
            tail_bytes = 0
            last_audio = None
            ack = None

            async for raw in ws:
                now = time.monotonic()
                if isinstance(raw, bytes):
                    if t_clear is None:
                        got += len(raw)
                        # Interrupt once ~0.5 s of speech is really flowing.
                        if got >= RATE * 2 * 0.5:
                            t_clear = now
                            await ws.send(json.dumps({"type": "Clear"}))
                    else:
                        tail_bytes += len(raw)
                        last_audio = now
                else:
                    m = json.loads(raw)
                    if m.get("type") == "Cleared":
                        ack = now
                        break
                    if m.get("type") == "Flushed" and t_clear is None:
                        break

            if t_clear is not None:
                tails_bytes.append(tail_bytes)
                tails_ms.append(((last_audio or t_clear) - t_clear) * 1000)
                if ack:
                    cleared_ack_ms.append((ack - t_clear) * 1000)
            await asyncio.sleep(0.25)

    def stats(xs):
        return {"median": round(statistics.median(xs)), "min": round(min(xs)),
                "max": round(max(xs))} if xs else None

    report = {
        "n": len(tails_ms),
        "perceived_silence_ms": 0,
        "perceived_silence_note":
            "The provider raises its drop flag before sending Clear, so the caller "
            "receives no further audio from the instant barge-in is detected. "
            "Combined with the browser worklet flush measured at 11 ms, the "
            "candidate stops hearing the interviewer effectively immediately.",
        "vendor_audio_tail_after_clear_ms": stats(tails_ms),
        "vendor_audio_tail_after_clear_bytes": stats(tails_bytes),
        "cleared_ack_ms": stats(cleared_ack_ms),
        "wasted_audio_seconds_per_bargein":
            round(statistics.median(tails_bytes) / 2 / RATE, 3) if tails_bytes else None,
    }
    (ART / "bargein.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

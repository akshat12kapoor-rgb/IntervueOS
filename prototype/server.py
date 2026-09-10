"""Prototype transport: one FastAPI app, one WebSocket, one static page.

Deliberately thin. All the interesting behaviour is in `session.py`; this file
only moves bytes between the browser and the session.

Wire protocol (browser <-> server)
  client -> server   binary : raw PCM16 mono @ 16 kHz
                     text   : {"type":"start", ...} | {"type":"playback_done"}
                              | {"type":"end"}
  server -> client   binary : raw PCM16 mono @ 24 kHz
                     text   : {"type":"state"|"transcript_partial"
                              |"transcript_final"|"interviewer_partial"
                              |"interrupt"|"ended"|"error", ...}
"""

from __future__ import annotations

import asyncio
import logging
import pathlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import CONFIG
from interview import InterviewState
from providers.anthropic_llm import AnthropicInterviewerLlm
from providers.deepgram_aura import DeepgramAuraTts
from providers.deepgram_flux import DeepgramFluxStt
from session import InterviewSession, SessionConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s"
)
log = logging.getLogger("intervueos.server")

STATIC = pathlib.Path(__file__).parent / "static"
app = FastAPI(title="IntervueOS prototype")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "deepgram_key": bool(CONFIG.deepgram_api_key),
        "anthropic_key": bool(CONFIG.anthropic_api_key),
        "models": {
            "llm": CONFIG.llm_model,
            "stt": CONFIG.stt_model,
            "tts": CONFIG.tts_model,
        },
    }


@app.websocket("/ws")
async def ws_interview(ws: WebSocket) -> None:
    await ws.accept()
    try:
        CONFIG.require("deepgram_api_key", "anthropic_api_key")
    except RuntimeError as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await ws.close()
        return

    try:
        setup = await asyncio.wait_for(ws.receive_json(), timeout=30)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await ws.close()
        return

    if setup.get("type") != "start":
        await ws.send_json({"type": "error", "message": "expected a start message"})
        await ws.close()
        return

    duration = min(
        int(setup.get("duration_s", 600)), CONFIG.max_interview_duration_s
    )
    topics = [t.strip() for t in setup.get("topics", []) if t.strip()] or [
        "your background",
        "a system you built",
        "how it failed",
    ]
    state = InterviewState(
        topics=topics,
        duration_s=duration,
        role=setup.get("role", "the role"),
    )

    stt = DeepgramFluxStt(
        api_key=CONFIG.deepgram_api_key,
        model=CONFIG.stt_model,
        sample_rate=CONFIG.stt_sample_rate,
        eot_threshold=CONFIG.eot_threshold,
        eager_eot_threshold=CONFIG.eager_eot_threshold,
        eot_timeout_ms=CONFIG.eot_timeout_ms,
    )
    tts = DeepgramAuraTts(
        api_key=CONFIG.deepgram_api_key,
        model=CONFIG.tts_model,
        sample_rate=CONFIG.tts_sample_rate,
    )
    llm = AnthropicInterviewerLlm(
        api_key=CONFIG.anthropic_api_key,
        model=CONFIG.llm_model,
        role=state.role,
        topics=topics,
        job_description=setup.get("job_description", "")[:20000],
        resume=setup.get("resume", "")[:20000],
        max_tokens=CONFIG.max_generation_tokens,
        state=state,
    )

    send_lock = asyncio.Lock()

    async def emit_json(payload: dict) -> None:
        async with send_lock:
            await ws.send_json(payload)

    async def emit_audio(chunk: bytes) -> None:
        async with send_lock:
            await ws.send_bytes(chunk)

    try:
        async with stt, tts:
            session = InterviewSession(
                stt=stt, tts=tts, llm=llm, state=state,
                emit_json=emit_json, emit_audio=emit_audio,
                config=SessionConfig(
                    transcript_window=CONFIG.transcript_window,
                    max_response_chars=CONFIG.max_response_chars,
                ),
            )
            await emit_json(
                {"type": "ready", "duration_s": duration, "topics": topics}
            )
            runner = asyncio.create_task(session.run(), name="session")
            receiver = asyncio.create_task(_receive(ws, session), name="receive")

            done, pending = await asyncio.wait(
                {runner, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            session.stop()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if (exc := task.exception()) is not None:
                    raise exc

            log.info("session summary: %s", session.summary())
            log.info("llm usage: %s", llm.usage)

    except WebSocketDisconnect:
        log.info("client disconnected")
    except Exception:
        log.exception("session failed")
        try:
            await emit_json(
                {"type": "error", "message": "The interview hit an error and stopped."}
            )
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def _receive(ws: WebSocket, session: InterviewSession) -> None:
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(1000)
        if (data := message.get("bytes")) is not None:
            await session.feed_audio(data)
        elif (text := message.get("text")) is not None:
            import json

            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            kind = payload.get("type")
            if kind == "playback_done":
                await session.note_playback_done()
            elif kind == "end":
                session.stop()
                return

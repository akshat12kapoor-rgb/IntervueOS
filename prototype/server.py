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
from providers.groq_llm import GroqInterviewerLlm
from providers.deepgram_aura import DeepgramAuraTts
from providers.deepgram_flux import DeepgramFluxStt
from providers.groq_tts import GroqOrpheusTts
from providers.groq_whisper import GroqWhisperStt
from session import InterviewSession, SessionConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s"
)
log = logging.getLogger("intervueos.server")

STATIC = pathlib.Path(__file__).parent / "static"
app = FastAPI(title="IntervueOS prototype")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _llm_key_name() -> str:
    return "groq_api_key" if CONFIG.llm_provider == "groq" else "anthropic_api_key"


def _llm_key() -> str:
    return getattr(CONFIG, _llm_key_name())


def _stt_key_name() -> str:
    return "groq_api_key" if CONFIG.stt_provider == "groq" else "deepgram_api_key"


def _tts_key_name() -> str:
    return "groq_api_key" if CONFIG.tts_provider == "groq" else "deepgram_api_key"


def _required_key_names() -> tuple[str, ...]:
    """The credentials this configuration actually needs.

    Deduplicated, because an all-Groq pipeline needs one key three times over
    and must not be told it is missing two others.
    """
    return tuple(
        dict.fromkeys((_stt_key_name(), _tts_key_name(), _llm_key_name()))
    )


def _term_hint(role: str, topics: list[str], job_description: str) -> str:
    """A spelling hint for Whisper's `prompt`, built from the session setup.

    Whisper treats `prompt` as a style/spelling prior, not an instruction, and
    caps it at 224 tokens — so this is a short bag of the words most likely to
    be mangled, not a sentence asking for anything. The job description is the
    best available source of a candidate's technical vocabulary, and it is
    already in memory.
    """
    head = job_description.strip().replace("\n", " ")[:400]
    topic_list = ", ".join(topics[:6])
    return (
        f"A technical interview for a {role} role. "
        f"Topics: {topic_list}. "
        f"Context: {head}"
    ).strip()


def _stt_model() -> str:
    return CONFIG.groq_stt_model if CONFIG.stt_provider == "groq" else CONFIG.stt_model


def _tts_model() -> str:
    return CONFIG.groq_tts_model if CONFIG.tts_provider == "groq" else CONFIG.tts_model


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "providers": {
            "stt": CONFIG.stt_provider,
            "tts": CONFIG.tts_provider,
            "llm": CONFIG.llm_provider,
        },
        "keys": {name: bool(getattr(CONFIG, name)) for name in _required_key_names()},
        "models": {
            "llm": CONFIG.llm_model,
            "stt": _stt_model(),
            "tts": _tts_model(),
        },
        "free_tier": CONFIG.stt_provider == CONFIG.tts_provider == CONFIG.llm_provider == "groq",
        # Speculative generation needs EagerEndOfTurn, which only Flux emits.
        "speculative": CONFIG.stt_provider == "deepgram",
    }


@app.websocket("/ws")
async def ws_interview(ws: WebSocket) -> None:
    await ws.accept()
    try:
        CONFIG.require(*_required_key_names())
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

    job_description = setup.get("job_description", "")[:20000]

    if CONFIG.stt_provider == "groq":
        stt = GroqWhisperStt(
            api_key=CONFIG.groq_api_key,
            model=CONFIG.groq_stt_model,
            sample_rate=CONFIG.stt_sample_rate,
            # Whisper's `prompt` is the fix for the term-recognition failure
            # Flux's `keyterm` silently ignored (docs/LATENCY.md). Feed it the
            # role and the job description, truncated hard — the parameter caps
            # at 224 tokens and the provider trims again.
            prompt=_term_hint(state.role, topics, job_description),
            end_silence_ms=CONFIG.vad_end_silence_ms,
            start_ms=CONFIG.vad_start_ms,
            preroll_ms=CONFIG.vad_preroll_ms,
            vad_aggressiveness=CONFIG.vad_aggressiveness,
            interim_interval_s=CONFIG.stt_interim_interval_s,
            requests_per_minute=CONFIG.stt_requests_per_minute,
            reserve_requests=CONFIG.stt_reserve_requests,
        )
    else:
        stt = DeepgramFluxStt(
            api_key=CONFIG.deepgram_api_key,
            model=CONFIG.stt_model,
            sample_rate=CONFIG.stt_sample_rate,
            eot_threshold=CONFIG.eot_threshold,
            eager_eot_threshold=CONFIG.eager_eot_threshold,
            eot_timeout_ms=CONFIG.eot_timeout_ms,
        )

    if CONFIG.tts_provider == "groq":
        tts = GroqOrpheusTts(
            api_key=CONFIG.groq_api_key,
            model=CONFIG.groq_tts_model,
            voice=CONFIG.groq_tts_voice,
            sample_rate=CONFIG.tts_sample_rate,
        )
    else:
        tts = DeepgramAuraTts(
            api_key=CONFIG.deepgram_api_key,
            model=CONFIG.tts_model,
            sample_rate=CONFIG.tts_sample_rate,
        )

    llm_cls = (
        GroqInterviewerLlm
        if CONFIG.llm_provider == "groq"
        else AnthropicInterviewerLlm
    )
    llm = llm_cls(
        api_key=_llm_key(),
        model=CONFIG.llm_model,
        role=state.role,
        topics=topics,
        job_description=job_description,
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
                    # Speculation needs EagerEndOfTurn. Only Flux emits it; the
                    # local VAD has no semantic signal to guess from (ADR-009).
                    # Leaving this on with a Groq STT would cost nothing but
                    # would be a lie in the logs, since no draft would ever be
                    # started.
                    speculate=CONFIG.stt_provider == "deepgram",
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

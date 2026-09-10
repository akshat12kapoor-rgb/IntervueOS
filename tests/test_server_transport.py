"""End-to-end through the real FastAPI handler.

The providers are swapped for scripted ones, but everything else — the WebSocket
handshake, the start message, binary audio in, JSON events and binary audio out,
teardown — is the code that actually runs in production. This is what catches
wiring mistakes that `test_voice_loop.py` cannot see, because that suite never
touches `server.py`.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from starlette.testclient import TestClient

import server
from providers.base import TurnEvent
from providers.scripted import RecordingTts, ScriptedLlm, ScriptedStt, turn

SCRIPT = [
    turn(TurnEvent.START_OF_TURN),
    turn(TurnEvent.UPDATE, "I built a payments"),
    turn(TurnEvent.END_OF_TURN, "I built a payments service on Postgres"),
]


def reconfigure(monkeypatch, **overrides) -> None:
    """Config is frozen on purpose — swap the whole object rather than mutate it."""
    monkeypatch.setattr(server, "CONFIG", dataclasses.replace(server.CONFIG, **overrides))


@pytest.fixture
def wired(monkeypatch):
    """Swap the vendor providers, keep the server."""
    reconfigure(monkeypatch, deepgram_api_key="test-key", anthropic_api_key="test-key")

    made: dict = {}

    def fake_stt(**_):
        made["stt"] = ScriptedStt(SCRIPT, gap=0.02, lead=0.35, tail=0.5)
        return made["stt"]

    def fake_tts(**_):
        made["tts"] = RecordingTts()
        return made["tts"]

    def fake_llm(**_):
        made["llm"] = ScriptedLlm(response="Why Postgres and not something else?")
        return made["llm"]

    monkeypatch.setattr(server, "DeepgramFluxStt", fake_stt)
    monkeypatch.setattr(server, "DeepgramAuraTts", fake_tts)
    monkeypatch.setattr(server, "AnthropicInterviewerLlm", fake_llm)
    return made


def _drain(ws, *, until: str, limit: int = 200):
    """Collect messages until `until` arrives or the socket closes."""
    events, audio_frames = [], 0
    for _ in range(limit):
        try:
            raw = ws.receive()
        except Exception:
            break
        if raw.get("type") == "websocket.close":
            break
        if raw.get("bytes") is not None:
            audio_frames += 1
            continue
        if raw.get("text") is not None:
            msg = json.loads(raw["text"])
            events.append(msg)
            if msg.get("type") == until:
                break
    return events, audio_frames


def test_full_interview_over_the_real_websocket(wired):
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "start",
                "role": "Senior Backend Engineer",
                "duration_s": 600,
                "topics": ["a system you designed", "how it failed"],
                "job_description": "Own our payments platform.",
                "resume": "Built a payments service at Acme.",
            })

            # Audio flows in as raw binary, exactly as the browser sends it.
            ws.send_bytes(b"\x00\x00" * 1280)

            events, audio_frames = _drain(ws, until="__never__", limit=60)
            ws.send_json({"type": "end"})

    kinds = [e["type"] for e in events]
    assert kinds[0] == "ready", "the client is told the interview is live"
    assert "state" in kinds
    assert "transcript_partial" in kinds, "interim transcripts reach the browser"
    assert "transcript_final" in kinds
    assert audio_frames > 0, "synthesised audio reaches the browser as binary frames"

    finals = [e for e in events if e["type"] == "transcript_final"]
    speakers = [f["speaker"] for f in finals]
    assert "interviewer" in speakers and "candidate" in speakers
    assert wired["stt"].audio_received == 2560, "browser audio reached the STT provider"


def test_start_message_is_required(wired):
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "playback_done"})
            events, _ = _drain(ws, until="error")
    assert events and events[0]["type"] == "error"


def test_requested_duration_cannot_exceed_the_configured_ceiling(wired, monkeypatch):
    reconfigure(
        monkeypatch,
        deepgram_api_key="test-key",
        anthropic_api_key="test-key",
        max_interview_duration_s=300,
    )
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "start", "duration_s": 99999, "topics": ["x"]})
            events, _ = _drain(ws, until="ready")
            ws.send_json({"type": "end"})
    ready = next(e for e in events if e["type"] == "ready")
    assert ready["duration_s"] == 300, "a client cannot buy itself a longer interview"


def test_missing_credentials_produce_a_clear_error(monkeypatch):
    reconfigure(monkeypatch, deepgram_api_key="", anthropic_api_key="")
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as ws:
            events, _ = _drain(ws, until="error")
    assert events[0]["type"] == "error"
    assert "DEEPGRAM_API_KEY" in events[0]["message"]

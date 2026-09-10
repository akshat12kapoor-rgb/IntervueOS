from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from interview import InterviewState
from providers.scripted import RecordingTts, ScriptedLlm, ScriptedStt
from session import InterviewSession, SessionConfig


@dataclass
class Harness:
    session: InterviewSession
    stt: ScriptedStt
    tts: RecordingTts
    llm: ScriptedLlm
    state: InterviewState
    events: list[dict] = field(default_factory=list)
    audio: list[bytes] = field(default_factory=list)
    at_interrupt: dict = field(default_factory=dict)
    """State captured at the instant the interrupt was emitted. Asserting on
    the end-of-session state instead would be satisfied by teardown, which
    cancels the same tasks — and would pass even with barge-in removed."""

    def of_type(self, kind: str) -> list[dict]:
        return [e for e in self.events if e.get("type") == kind]

    @property
    def transcript(self) -> list[tuple[str, str]]:
        return [(t.speaker, t.text) for t in self.state.turns]


@pytest.fixture
def harness():
    def _build(script, *, speculate=True, response="Why did you choose that?",
               llm_delay=0.02, topics=None, duration_s=600.0, gap=0.01, tail=0.4,
               lead=0.0, auto_playback_done=True):
        stt = ScriptedStt(script, gap=gap, tail=tail, lead=lead)
        tts = RecordingTts()
        llm = ScriptedLlm(response=response, delay=llm_delay)
        state = InterviewState(
            topics=topics or ["system design", "databases", "failure modes"],
            duration_s=duration_s,
        )
        h = Harness(session=None, stt=stt, tts=tts, llm=llm, state=state)  # type: ignore

        async def emit_json(payload: dict) -> None:
            h.events.append(payload)
            if payload.get("type") == "interrupt":
                h.at_interrupt = {
                    "llm_cancelled": llm.cancelled,
                    "tts_clears": tts.clears,
                    "tts_chars": len("".join(tts.spoken)),
                }
            # Stand in for a real browser: once an interviewer turn is fully
            # delivered, the client reports that its playback queue drained.
            # Without this the session believes audio is still in flight and
            # treats the candidate's next turn as a barge-in.
            if (
                auto_playback_done
                and payload.get("type") == "transcript_final"
                and payload.get("speaker") == "interviewer"
                and not payload.get("interrupted")
            ):
                asyncio.get_running_loop().call_soon(
                    lambda: asyncio.ensure_future(h.session.note_playback_done())
                )

        async def emit_audio(chunk: bytes) -> None:
            h.audio.append(chunk)

        h.session = InterviewSession(
            stt=stt, tts=tts, llm=llm, state=state,
            emit_json=emit_json, emit_audio=emit_audio,
            config=SessionConfig(speculate=speculate),
        )
        return h

    return _build


async def run(h: Harness, timeout: float = 5.0) -> Harness:
    await asyncio.wait_for(h.session.run(), timeout=timeout)
    return h

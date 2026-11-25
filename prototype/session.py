"""The voice loop orchestrator.

Owns turn-taking, barge-in, speculative generation, and cancellation. Imports
no vendor code — only the Protocols in `providers.base`, which is what makes it
testable against scripted providers.

The three things that make the conversation feel human, in order of impact:

1. **Barge-in.** The instant the candidate starts speaking we cancel the
   in-flight LLM generation, tell the TTS vendor to discard its buffer, and tell
   the browser to flush its playback queue. All three, or the interviewer talks
   over the candidate.

2. **Speculative generation.** Deepgram Flux emits `EagerEndOfTurn` when it has
   moderate confidence the candidate has stopped. We start generating *then*,
   several hundred milliseconds before `EndOfTurn`. If the candidate resumes,
   Flux sends `TurnResumed` and we throw the draft away. When the guess is right
   — most of the time — the response is already buffered and starts speaking
   essentially immediately.

3. **Sentence-level TTS streaming.** We hand the TTS vendor each sentence as the
   LLM completes it rather than waiting for the whole response.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from interview import InterviewState, Objective, Turn
from providers.base import LlmProvider, SttEvent, SttProvider, TtsProvider, TurnEvent

log = logging.getLogger("intervueos.session")


class Floor(enum.Enum):
    """Who currently has the conversational floor."""

    CANDIDATE = "candidate"
    INTERVIEWER = "interviewer"
    ENDED = "ended"


@dataclass(slots=True)
class SessionConfig:
    transcript_window: int = 12
    """How many recent turns are sent to the LLM. The rest is represented by
    InterviewState, not raw text — this is what keeps per-turn cost flat as the
    interview grows."""

    speculate: bool = True
    """Use EagerEndOfTurn to start generating early."""

    max_response_chars: int = 400
    """A spoken interviewer turn should be short. Hard ceiling, enforced here
    rather than trusted to the prompt."""

    min_answer_words: int = 5
    """Below this, an ended turn is treated as a thinking pause rather than an
    answer, and the interviewer waits instead of asking something new.

    Flux ends a turn when it stops hearing speech. A human who pauses to think
    mid-sentence therefore produces a complete-looking turn containing three
    words. Responding to that asks a fresh question over the top of someone
    who had not finished, and because their next words then arrive as another
    short turn, it cascades into rapid-fire questioning. Observed live
    2026-11-25; the thresholds in docs/LATENCY.md were swept against synthetic
    speech, which never hesitates.

    Kept low: a real answer can be six words ("I used Redis and Kafka
    together"), and holding one only costs `pause_grace_s`."""

    pause_grace_s: float = 2.5
    """How long to wait for the candidate to resume before treating a short
    turn as their whole answer."""

    max_pause_holds: int = 3
    """Cap on consecutive holds, so silence cannot stall the interview."""


@dataclass(slots=True)
class _Draft:
    """An in-flight speculative generation."""

    source_transcript: str
    objective: Objective
    task: asyncio.Task
    queue: asyncio.Queue


EmitJson = Callable[[dict], Awaitable[None]]
EmitAudio = Callable[[bytes], Awaitable[None]]


class InterviewSession:
    def __init__(
        self,
        *,
        stt: SttProvider,
        tts: TtsProvider,
        llm: LlmProvider,
        state: InterviewState,
        emit_json: EmitJson,
        emit_audio: EmitAudio,
        config: SessionConfig | None = None,
    ) -> None:
        self.stt = stt
        self.tts = tts
        self.llm = llm
        self.state = state
        self.emit_json = emit_json
        self.emit_audio = emit_audio
        self.config = config or SessionConfig()

        self.floor = Floor.CANDIDATE
        self._draft: _Draft | None = None
        self._speak_task: asyncio.Task | None = None
        self._audio_in_flight = False
        self._candidate_turn_started: float = 0.0
        self._stop = asyncio.Event()
        self._held_text: str = ""
        self._holds: int = 0
        self._hold_timer: asyncio.Task | None = None

        # Instrumentation — real numbers, reported at the end of the session.
        self.metrics: dict[str, list[float]] = {
            "eot_to_first_audio_ms": [],
            "speculation_hits": [],
            "barge_ins": [],
            "pause_holds": [],
        }

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Drive the session until the interview ends or the transport closes."""
        pump_audio = asyncio.create_task(self._pump_tts_audio(), name="tts-audio")
        try:
            await self._open()
            await self._pump_stt_events()
        finally:
            pump_audio.cancel()
            await _quiet(pump_audio)
            self._cancel_hold_timer()
            # Whatever was being held when the stream closed is still
            # something the candidate said. Record it — losing it would also
            # lose it from the report — but do not start a reply we cannot
            # deliver.
            if self._held_text:
                self.state.record(
                    Turn(
                        speaker="candidate",
                        text=self._held_text,
                        topic=self.state.current_topic,
                        started_at=self._candidate_turn_started or time.monotonic(),
                        ended_at=time.monotonic(),
                    )
                )
                self._held_text = ""
            await self._cancel_draft()
            await self._cancel_speaking()

    async def _open(self) -> None:
        """Speak the opening question. The interviewer starts, as in a real
        interview — the candidate should not have to work out when to begin."""
        objective = Objective.OPEN
        self.state.apply_objective(objective)
        await self._respond(objective, self.state.recent(self.config.transcript_window))

    async def feed_audio(self, pcm16: bytes) -> None:
        if self.floor is not Floor.ENDED:
            await self.stt.send_audio(pcm16)

    async def note_playback_done(self) -> None:
        """The browser's playback queue has drained. Only the client knows this
        precisely, so it tells us."""
        self._audio_in_flight = False
        if self.floor is Floor.INTERVIEWER:
            await self._give_floor_to_candidate()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # STT event handling — the core state machine
    # ------------------------------------------------------------------

    async def _pump_stt_events(self) -> None:
        async for ev in self.stt.events():
            if self._stop.is_set() or self.floor is Floor.ENDED:
                break
            await self._on_stt_event(ev)

    async def _on_stt_event(self, ev: SttEvent) -> None:
        match ev.event:
            case TurnEvent.START_OF_TURN:
                await self._on_start_of_turn(ev)
            case TurnEvent.UPDATE:
                await self.emit_json(
                    {"type": "transcript_partial", "text": ev.transcript}
                )
            case TurnEvent.EAGER_END_OF_TURN:
                await self._on_eager_end_of_turn(ev)
            case TurnEvent.TURN_RESUMED:
                await self._on_turn_resumed(ev)
            case TurnEvent.END_OF_TURN:
                await self._on_end_of_turn(ev)

    async def _on_start_of_turn(self, ev: SttEvent) -> None:
        self._candidate_turn_started = time.monotonic()
        # They resumed inside the grace window: this is one answer with a
        # pause in it, not two answers.
        self._cancel_hold_timer()
        if self.floor is Floor.INTERVIEWER or self._audio_in_flight:
            await self._barge_in()
        self.floor = Floor.CANDIDATE
        await self.emit_json({"type": "state", "floor": "candidate"})

    async def _on_eager_end_of_turn(self, ev: SttEvent) -> None:
        """Flux thinks they might be done. Start generating, but do not speak."""
        if not self.config.speculate:
            return
        if self._draft is not None or self.floor is not Floor.CANDIDATE:
            return
        if not ev.transcript.strip():
            return

        objective = self._choose_objective(ev.transcript)
        history = [
            *self.state.recent(self.config.transcript_window),
            ("candidate", ev.transcript),
        ]
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(
            self._collect(history, objective, queue), name="draft"
        )
        self._draft = _Draft(ev.transcript, objective, task, queue)
        log.debug("speculating on %r", ev.transcript[-60:])

    async def _on_turn_resumed(self, ev: SttEvent) -> None:
        """They were not done. Throw the draft away."""
        if self._draft is not None:
            log.debug("turn resumed, discarding draft")
            await self._cancel_draft()

    def _cancel_hold_timer(self) -> None:
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    async def _on_end_of_turn(self, ev: SttEvent) -> None:
        text = " ".join(x for x in (self._held_text, ev.transcript.strip()) if x)
        now = time.monotonic()

        if not text:
            # Flux ended a turn with nothing in it (noise, a cough). Do not
            # burn an interviewer turn on silence.
            await self._cancel_draft()
            return

        # A short turn is more likely a pause for thought than a finished
        # answer. Hold it and give them a moment to carry on.
        if (
            len(text.split()) < self.config.min_answer_words
            and self._holds < self.config.max_pause_holds
            and not self.state.is_over
        ):
            self._held_text = text
            self._holds += 1
            self._cancel_hold_timer()
            await self._cancel_draft()
            self._hold_timer = asyncio.create_task(
                self._flush_after_grace(), name="pause-grace"
            )
            log.info("holding short turn (%d words), hold %d/%d: %r",
                     len(text.split()), self._holds,
                     self.config.max_pause_holds, text)
            return

        self._cancel_hold_timer()
        self.metrics["pause_holds"].append(float(self._holds))
        self._held_text = ""
        self._holds = 0

        await self._commit_answer(text, now)

    async def _flush_after_grace(self) -> None:
        """They did not resume. Treat what we held as the whole answer."""
        try:
            await asyncio.sleep(self.config.pause_grace_s)
        except asyncio.CancelledError:
            return
        text, self._held_text = self._held_text, ""
        self.metrics["pause_holds"].append(float(self._holds))
        self._holds = 0
        self._hold_timer = None
        if text and not self.state.is_over:
            await self._commit_answer(text, time.monotonic())

    async def _commit_answer(self, text: str, now: float) -> None:
        self.state.record(
            Turn(
                speaker="candidate",
                text=text,
                topic=self.state.current_topic,
                started_at=self._candidate_turn_started or now,
                ended_at=now,
            )
        )
        await self.emit_json({"type": "transcript_final", "speaker": "candidate", "text": text})

        if self.state.is_over:
            await self._end_interview()
            return

        draft = self._take_matching_draft(text)
        history = self.state.recent(self.config.transcript_window)

        if draft is not None:
            self.metrics["speculation_hits"].append(1.0)
            await self._respond(draft.objective, history, prepared=draft, eot_at=now)
        else:
            self.metrics["speculation_hits"].append(0.0)
            await self._cancel_draft()
            objective = self._choose_objective(text)
            await self._respond(objective, history, eot_at=now)

    def _take_matching_draft(self, final_transcript: str) -> _Draft | None:
        """A draft is usable only if it was generated from what the candidate
        actually ended up saying. Anything else and we would be answering a
        question they did not finish asking."""
        draft = self._draft
        if draft is None:
            return None
        if _normalise(draft.source_transcript) != _normalise(final_transcript):
            return None
        self._draft = None
        return draft

    # ------------------------------------------------------------------
    # generation + speech
    # ------------------------------------------------------------------

    def _choose_objective(self, pending_candidate_text: str) -> Objective:
        """Objective selection reads state *including* the turn about to be
        committed, so speculation and the committed path agree."""
        probe = Turn(speaker="candidate", text=pending_candidate_text)
        self.state.turns.append(probe)
        try:
            return self.state.next_objective()
        finally:
            self.state.turns.pop()

    async def _collect(
        self,
        history: Sequence[tuple[str, str]],
        objective: Objective,
        queue: asyncio.Queue,
    ) -> None:
        """Run the LLM and push fragments into `queue`. `None` marks the end.

        Fragments generated before the draft is committed simply sit in the
        queue — that buffering *is* the latency win.
        """
        total = 0
        try:
            async for fragment in self.llm.generate(history, objective.value):
                total += len(fragment)
                if total > self.config.max_response_chars:
                    break
                await queue.put(fragment)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("generation failed")
            await queue.put(
                " Sorry, could you give me a moment? Let's continue — "
                "please carry on with what you were saying."
            )
        finally:
            await queue.put(None)

    async def _respond(
        self,
        objective: Objective,
        history: Sequence[tuple[str, str]],
        *,
        prepared: _Draft | None = None,
        eot_at: float | None = None,
    ) -> None:
        await self._cancel_speaking()

        if prepared is not None:
            queue, gen_task = prepared.queue, prepared.task
        else:
            queue = asyncio.Queue()
            gen_task = asyncio.create_task(
                self._collect(history, objective, queue), name="generate"
            )

        self.floor = Floor.INTERVIEWER
        self.state.apply_objective(objective)
        await self.emit_json(
            {"type": "state", "floor": "interviewer", "objective": objective.value}
        )
        self._speak_task = asyncio.create_task(
            self._speak(objective, queue, gen_task, eot_at), name="speak"
        )

    async def _speak(
        self,
        objective: Objective,
        queue: asyncio.Queue,
        gen_task: asyncio.Task,
        eot_at: float | None,
    ) -> None:
        spoken: list[str] = []
        buffer = ""
        started = time.monotonic()
        first_audio_sent = False
        interrupted = False

        try:
            while True:
                fragment = await queue.get()
                if fragment is None:
                    break
                spoken.append(fragment)
                buffer += fragment
                await self.emit_json({"type": "interviewer_partial", "text": fragment})

                while (split := _pop_sentence(buffer)) is not None:
                    sentence, buffer = split
                    await self.tts.speak(sentence)
                    if not first_audio_sent:
                        first_audio_sent = True
                        self._audio_in_flight = True
                        if eot_at is not None:
                            self.metrics["eot_to_first_audio_ms"].append(
                                (time.monotonic() - eot_at) * 1000
                            )

            if buffer.strip():
                await self.tts.speak(buffer)
                self._audio_in_flight = True
            await self.tts.flush()

        except asyncio.CancelledError:
            interrupted = True
            raise
        finally:
            text = "".join(spoken).strip()
            if text:
                self.state.record(
                    Turn(
                        speaker="interviewer",
                        text=text,
                        topic=self.state.current_topic,
                        objective=objective,
                        started_at=started,
                        ended_at=time.monotonic(),
                        interrupted=interrupted,
                    )
                )
                await self.emit_json(
                    {
                        "type": "transcript_final",
                        "speaker": "interviewer",
                        "text": text,
                        "interrupted": interrupted,
                    }
                )
            if not gen_task.done():
                gen_task.cancel()
                await _quiet(gen_task)

    async def _pump_tts_audio(self) -> None:
        async for chunk in self.tts.audio():
            await self.emit_audio(chunk)

    # ------------------------------------------------------------------
    # interruption
    # ------------------------------------------------------------------

    async def _barge_in(self) -> None:
        """Cancel everything the interviewer was doing, in the order that keeps
        the least audio playing: stop producing, stop synthesising, stop
        playing."""
        self.metrics["barge_ins"].append(1.0)
        log.debug("barge-in")
        await self._cancel_speaking()
        await self._cancel_draft()
        try:
            await self.tts.clear()
        except Exception:
            log.exception("tts.clear failed during barge-in")
        self._audio_in_flight = False
        await self.emit_json({"type": "interrupt"})

    async def _cancel_speaking(self) -> None:
        task, self._speak_task = self._speak_task, None
        if task is not None and not task.done():
            task.cancel()
            await _quiet(task)

    async def _cancel_draft(self) -> None:
        draft, self._draft = self._draft, None
        if draft is not None and not draft.task.done():
            draft.task.cancel()
            await _quiet(draft.task)

    async def _give_floor_to_candidate(self) -> None:
        self.floor = Floor.CANDIDATE
        await self.emit_json({"type": "state", "floor": "candidate"})

    async def _end_interview(self) -> None:
        self.state.mark_ended()
        self.floor = Floor.ENDED
        await self.emit_json({"type": "ended", "summary": self.summary()})
        self._stop.set()

    def summary(self) -> dict:
        hits = self.metrics["speculation_hits"]
        lat = self.metrics["eot_to_first_audio_ms"]
        return {
            "turns": len(self.state.turns),
            "elapsed_s": round(self.state.elapsed, 1),
            "topics_covered": self.state.topics_covered,
            "barge_ins": len(self.metrics["barge_ins"]),
            "speculation_hit_rate": round(sum(hits) / len(hits), 2) if hits else None,
            "median_eot_to_first_audio_ms": round(_median(lat)) if lat else None,
        }


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

_SENTENCE_END = re.compile(r"([.!?])(\s|$)")
_CLAUSE_END = re.compile(r"([,;:])(\s)")


def _pop_sentence(buffer: str, soft_limit: int = 90) -> tuple[str, str] | None:
    """Pull one speakable chunk off the front of `buffer`.

    Sentence boundary first; failing that, a clause boundary once the buffer is
    long enough that waiting would delay speech audibly. Returns None when there
    is nothing worth sending yet.
    """
    m = _SENTENCE_END.search(buffer)
    if m:
        cut = m.end(1)
        return buffer[:cut].strip(), buffer[cut:].lstrip()
    if len(buffer) >= soft_limit:
        for m in _CLAUSE_END.finditer(buffer):
            if m.end(1) >= soft_limit // 2:
                cut = m.end(1)
                return buffer[:cut].strip(), buffer[cut:].lstrip()
    return None


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


async def _quiet(task: asyncio.Task) -> None:
    """Await a cancelled task without letting its exception escape."""
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

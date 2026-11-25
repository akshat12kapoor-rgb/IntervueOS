"""Turn-taking, barge-in, and speculative generation.

These are the behaviours that decide whether the conversation feels human, so
they are tested against scripted providers rather than left to manual QA.
"""

from __future__ import annotations

import pytest

from conftest import run
from interview import Objective
from providers.base import TurnEvent
from providers.scripted import turn
from session import Floor


async def test_interviewer_opens_the_conversation(harness):
    h = await run(harness([]))
    assert h.llm.calls, "the interviewer must speak first"
    assert h.llm.calls[0][1] == Objective.OPEN.value
    assert "".join(h.tts.spoken).strip(), "opening question reached TTS"
    assert h.tts.flushes >= 1
    assert h.transcript[0][0] == "interviewer"


async def test_a_completed_answer_produces_exactly_one_follow_up(harness):
    h = await run(harness(
        [turn(TurnEvent.START_OF_TURN),
         turn(TurnEvent.UPDATE, "I used Redis"),
         turn(TurnEvent.END_OF_TURN, "I used Redis for the session store")],
        speculate=False, lead=0.3,
    ))
    # one opening question + one follow-up
    assert len(h.llm.calls) == 2
    speakers = [s for s, _ in h.transcript]
    assert speakers == ["interviewer", "candidate", "interviewer"]


async def test_partial_transcripts_reach_the_client(harness):
    h = await run(harness(
        [turn(TurnEvent.START_OF_TURN), turn(TurnEvent.UPDATE, "I used Red")],
        lead=0.3,
    ))
    assert [e["text"] for e in h.of_type("transcript_partial")] == ["I used Red"]


# ---------------------------------------------------------------- barge-in


async def test_candidate_speaking_interrupts_the_interviewer(harness):
    """The whole product depends on this one."""
    h = await run(harness(
        [turn(TurnEvent.START_OF_TURN)],       # arrives while the opener is generating
        response="This is a deliberately long opening question that takes a while to generate",
        llm_delay=0.05,
    ))
    assert h.of_type("interrupt"), "the browser must be told to flush playback"
    # Measured at the moment of the interrupt, not at the end of the session —
    # teardown cancels the same tasks and would mask a broken barge-in.
    assert h.at_interrupt["llm_cancelled"] >= 1, "in-flight generation must be cancelled"
    assert h.at_interrupt["tts_clears"] >= 1, "the TTS vendor's buffer must be discarded"
    assert h.session.floor is Floor.CANDIDATE
    # Nothing further may be handed to TTS after the interrupt.
    assert len("".join(h.tts.spoken)) == h.at_interrupt["tts_chars"]


async def test_an_interrupted_turn_is_recorded_as_interrupted(harness):
    h = await run(harness(
        [turn(TurnEvent.START_OF_TURN)],
        response="A long opening question with many words so it is still mid-flight",
        llm_delay=0.05, gap=0.12,
    ))
    finals = [e for e in h.of_type("transcript_final") if e["speaker"] == "interviewer"]
    assert finals and finals[0]["interrupted"] is True, (
        "the record must show the candidate only heard part of this question"
    )


async def test_no_barge_in_when_the_candidate_waits_their_turn(harness):
    h = await run(harness(
        [turn(TurnEvent.START_OF_TURN)],
        response="Short.",
        llm_delay=0.001,
        lead=0.3,                              # opener finishes before they speak
    ))
    assert h.tts.clears == 0
    assert not h.of_type("interrupt")


# --------------------------------------------------------- speculation


async def test_eager_end_of_turn_starts_generating_before_the_turn_ends(harness):
    """The latency win: when Flux's early guess is right, the response is
    already buffered and no second generation is needed."""
    answer = "I used Redis for the session store"
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.EAGER_END_OF_TURN, answer),
        turn(TurnEvent.END_OF_TURN, answer),
    ], lead=0.3))
    assert len(h.llm.calls) == 2, "opener + one speculative call reused, not regenerated"
    assert h.session.summary()["speculation_hit_rate"] == 1.0


async def test_turn_resumed_throws_the_draft_away(harness):
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.EAGER_END_OF_TURN, "I used Redis"),
        turn(TurnEvent.TURN_RESUMED, "I used Redis"),
        turn(TurnEvent.END_OF_TURN, "I used Redis but then moved to Postgres"),
    ], lead=0.3))
    assert h.llm.cancelled >= 1, "the speculative draft must be cancelled"
    assert len(h.llm.calls) == 3, "opener + discarded draft + real generation"
    assert h.session.summary()["speculation_hit_rate"] == 0.0


async def test_a_draft_built_from_the_wrong_words_is_discarded(harness):
    """Guards the case where TurnResumed never arrives but the final transcript
    differs anyway — answering a half-finished sentence is worse than waiting."""
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.EAGER_END_OF_TURN, "I used Redis for the hot path"),
        turn(TurnEvent.END_OF_TURN,
             "I used Redis for the hot path and Kafka for the write log"),
    ], lead=0.3))
    assert h.session.summary()["speculation_hit_rate"] == 0.0
    assert len(h.llm.calls) == 3


async def test_speculation_tolerates_punctuation_and_casing_drift(harness):
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.EAGER_END_OF_TURN, "i used redis for the session store"),
        turn(TurnEvent.END_OF_TURN, "I used Redis for the session store."),
    ], lead=0.3))
    assert h.session.summary()["speculation_hit_rate"] == 1.0


async def test_speculation_can_be_disabled(harness):
    answer = "I used Redis for the session store"
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.EAGER_END_OF_TURN, answer),
        turn(TurnEvent.END_OF_TURN, answer),
    ], speculate=False, lead=0.3))
    assert len(h.llm.calls) == 2, "no draft; one generation at EndOfTurn"


# ------------------------------------------------------------- edge cases


async def test_an_empty_turn_does_not_burn_an_interviewer_question(harness):
    """A cough or a door slam can end a turn with no words in it."""
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.END_OF_TURN, "   "),
    ], lead=0.3))
    assert len(h.llm.calls) == 1, "only the opening question"
    assert [s for s, _ in h.transcript] == ["interviewer"]


async def test_the_interview_ends_itself_when_time_runs_out(harness):
    h = harness([turn(TurnEvent.START_OF_TURN), turn(TurnEvent.END_OF_TURN, "Done talking")],
                lead=0.3)
    h.state.started_at -= h.state.duration_s + 1
    await run(h)
    assert h.of_type("ended"), "the session must close itself, not run forever"
    assert h.session.floor is Floor.ENDED


async def test_generation_failure_does_not_kill_the_interview(harness):
    class Exploding:
        cancelled = 0
        calls: list = []

        async def generate(self, transcript, instruction):
            self.calls.append((transcript, instruction))
            raise RuntimeError("provider is down")
            yield  # pragma: no cover

    h = harness([])
    h.session.llm = h.llm = Exploding()  # type: ignore
    await run(h)
    assert h.tts.spoken, "the candidate hears a graceful recovery line, not silence"
    assert h.tts.flushes >= 1


async def test_audio_from_the_client_reaches_the_stt_provider(harness):
    h = harness([])
    await h.session.feed_audio(b"\x00\x01" * 1280)
    assert h.stt.audio_received == 2560


async def test_summary_reports_real_measurements(harness):
    answer = "I used Redis for the session store"
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.EAGER_END_OF_TURN, answer),
        turn(TurnEvent.END_OF_TURN, answer),
    ], lead=0.3))
    s = h.session.summary()
    assert s["turns"] >= 3
    assert s["speculation_hit_rate"] == 1.0
    assert s["median_eot_to_first_audio_ms"] is not None

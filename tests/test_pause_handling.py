"""A pause for thought is not an answer.

Observed live 2026-11-25: the interviewer asked a question, the candidate
paused before replying, and the interviewer fired off question after question.
Flux ends a turn when speech stops, so a hesitation produces a complete-looking
turn with three words in it. Responding to that asks over the top of someone
mid-thought, and their next words then arrive as another short turn — which is
what made it cascade rather than misfire once.

`llm.calls` is the assertion that matters here: one entry per question the
interviewer decided to ask.
"""

from __future__ import annotations

import pytest

from conftest import run
from providers.base import TurnEvent
from providers.scripted import turn


@pytest.mark.asyncio
async def test_a_short_fragment_does_not_burn_a_question(harness):
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.END_OF_TURN, "So, um"),
    ], tail=1.0))
    assert len(h.llm.calls) == 1, "only the opening question — the pause drew no reply"


@pytest.mark.asyncio
async def test_fragments_either_side_of_a_pause_become_one_answer(harness):
    """The reported cascade in miniature: two fragments, one question back."""
    h = harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.END_OF_TURN, "So the system"),
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.END_OF_TURN, "handled about twelve thousand writes a second"),
    ], tail=1.5)
    h.session.config.pause_grace_s = 0.2
    await run(h, timeout=10.0)

    candidate = [t for t in h.state.turns if t.speaker == "candidate"]
    assert len(candidate) == 1, "the fragments are one answer, not two"
    assert candidate[0].text == "So the system handled about twelve thousand writes a second"
    assert len(h.llm.calls) == 2, "opening question, then one reply — not three"


@pytest.mark.asyncio
async def test_a_substantial_answer_is_answered_immediately(harness):
    """The fix must not add latency to a normal answer."""
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.END_OF_TURN,
             "I rewrote the ingestion pipeline and moved it from batch to streaming"),
    ], tail=1.0))
    assert h.session.metrics["pause_holds"] == [0.0], "no hold for a full answer"
    assert len(h.llm.calls) == 2


@pytest.mark.asyncio
async def test_a_candidate_who_never_resumes_still_gets_a_reply(harness):
    """Holding must not strand anyone: after the grace window the interviewer
    answers what it has."""
    h = harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.END_OF_TURN, "Yes exactly"),
    ], tail=1.5)
    h.session.config.pause_grace_s = 0.2
    await run(h, timeout=10.0)

    candidate = [t for t in h.state.turns if t.speaker == "candidate"]
    assert [t.text for t in candidate] == ["Yes exactly"]
    assert len(h.llm.calls) == 2
    assert h.session.metrics["pause_holds"] == [1.0], "held once, then flushed"


@pytest.mark.asyncio
async def test_nothing_the_candidate_said_is_lost_when_the_stream_closes(harness):
    """A held fragment is still something they said, and the report reads the
    transcript — dropping it would silently lose an answer."""
    h = await run(harness([
        turn(TurnEvent.START_OF_TURN),
        turn(TurnEvent.END_OF_TURN, "Briefly yes"),
    ], tail=0.3))
    assert [t.text for t in h.state.turns if t.speaker == "candidate"] == ["Briefly yes"]


@pytest.mark.asyncio
async def test_repeated_fragments_cannot_stall_the_interview(harness):
    """Past max_pause_holds the interviewer proceeds, so a monosyllabic
    candidate still gets an interview rather than silence."""
    script = [turn(TurnEvent.START_OF_TURN)]
    for _ in range(5):
        script.append(turn(TurnEvent.END_OF_TURN, "um"))
        script.append(turn(TurnEvent.START_OF_TURN))
    h = harness(script, tail=1.5)
    h.session.config.pause_grace_s = 0.2
    await run(h, timeout=12.0)
    assert len(h.llm.calls) >= 2, "the held fragments were eventually answered"

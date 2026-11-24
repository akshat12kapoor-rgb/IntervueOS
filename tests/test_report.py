"""The deterministic half of the report, and the route that serves it.

`build_evidence` is where a report can go quietly wrong — pairing an answer
with the wrong question, or scoring one that was never given. None of that
needs a model, so none of it is tested against one.
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

import server
from interview import InterviewState, Objective, Turn
from report import build_evidence, coverage_note


def _state(*turns: Turn, topics=None, duration=600.0) -> InterviewState:
    st = InterviewState(
        topics=topics or ["system design", "failure modes"],
        duration_s=duration,
        role="Senior Backend Engineer",
    )
    for t in turns:
        st.record(t)
    return st


def q(text, objective=Objective.PROBE, topic="system design") -> Turn:
    return Turn(speaker="interviewer", text=text, topic=topic, objective=objective)


def a(text, *, start=0.0, end=4.0, interrupted=False) -> Turn:
    return Turn(speaker="candidate", text=text, started_at=start,
                ended_at=end, interrupted=interrupted)


# ----------------------------------------------------------------- evidence

def test_each_question_is_paired_with_the_answer_it_drew():
    ev = build_evidence(_state(
        q("What did you build?", Objective.OPEN),
        a("A payments pipeline doing 12k requests a second."),
        q("Why Postgres?", Objective.CHALLENGE),
        a("We already ran it, and the ops cost of another store was real."),
    ))
    assert [e.question for e in ev.exchanges] == ["What did you build?", "Why Postgres?"]
    assert ev.exchanges[0].answer.startswith("A payments pipeline")
    assert ev.exchanges[1].answer.startswith("We already ran it")
    assert [e.index for e in ev.exchanges] == [1, 2]


def test_the_recorded_objective_survives_into_the_report():
    """The whole point of the objective/phrasing split: the report can state
    what was being tested without asking a model to guess."""
    ev = build_evidence(_state(
        q("What exactly did you do?", Objective.SPECIFICITY),
        a("I wrote the consumer and the replay tool."),
    ))
    assert ev.exchanges[0].objective == "specificity"
    assert "concretely" in ev.exchanges[0].intent


def test_a_question_that_drew_no_answer_is_marked_unanswered():
    """Two interviewer turns in a row — a barge-in can leave this. Scoring the
    second against the first's answer would be wrong."""
    ev = build_evidence(_state(
        q("First question?"),
        q("Second question?"),
        a("Only this one got answered."),
    ))
    assert ev.exchanges[0].answered is False
    assert ev.exchanges[0].answer == ""
    assert ev.exchanges[1].answered is True


def test_a_trailing_question_with_no_reply_is_unanswered():
    ev = build_evidence(_state(q("Time ran out mid-question?")))
    assert ev.exchanges[0].answered is False


def test_whitespace_only_answer_does_not_count_as_answered():
    ev = build_evidence(_state(q("Anything?"), a("   ")))
    assert ev.exchanges[0].answered is False


def test_navigation_turns_are_excluded_from_the_probing_set():
    """next_topic and wrap_up are steering, not examination. Scoring them
    would drag an otherwise fine interview down."""
    ev = build_evidence(_state(
        q("Tell me about failure modes.", Objective.NEXT_TOPIC),
        a("Sure."),
        q("What broke?", Objective.PROBE),
        a("The consumer lagged behind by twenty minutes."),
        q("Thanks, we are out of time.", Objective.WRAP_UP),
        a("Thank you."),
    ))
    assert len(ev.exchanges) == 3
    assert [e.index for e in ev.probing] == [2]


def test_answer_length_and_interruption_are_recorded():
    ev = build_evidence(_state(
        q("Go on?"), a("Cut off mid", start=1.0, end=3.5, interrupted=True),
    ))
    assert ev.exchanges[0].answer_words == 3
    assert ev.exchanges[0].answer_seconds == 2.5
    assert ev.exchanges[0].interrupted is True


def test_evidence_is_json_serialisable():
    """It is handed straight to a provider as JSON; a dataclass left in place
    would fail at the network boundary rather than here."""
    ev = build_evidence(_state(q("What?"), a("This.")))
    assert json.loads(json.dumps(ev.to_dict()))["exchanges"][0]["index"] == 1


# ------------------------------------------------------------------ caveats

def test_a_thin_interview_is_flagged():
    ev = build_evidence(_state(q("One question?"), a("One answer."), duration=120.0))
    note = coverage_note(ev)
    assert note and "lightly" in note
    assert "failure modes" in note  # never reached


def test_a_full_interview_gets_no_caveat():
    turns = []
    for i in range(5):
        turns += [q(f"Question {i}?"), a(f"A reasonably substantial answer number {i}.")]
    st = _state(*turns, topics=["system design"], duration=600.0)
    st.advance_topic()
    ev = build_evidence(st)
    ev_long = type(ev)(role=ev.role, topics=["system design"],
                       topics_covered=["system design"], duration_s=600.0,
                       exchanges=ev.exchanges)
    assert coverage_note(ev_long) is None


# ------------------------------------------------------------------- routes

def test_unknown_report_is_a_404():
    with TestClient(server.app) as client:
        assert client.get("/api/report/does-not-exist").status_code == 404


def test_a_pending_report_reports_itself_as_pending(monkeypatch):
    """The page polls on this, so it must be distinguishable from ready."""
    monkeypatch.setitem(server._REPORTS, "abc123", {"status": "pending"})
    with TestClient(server.app) as client:
        assert client.get("/api/report/abc123").json() == {"status": "pending"}


def test_the_report_page_is_served_for_any_id():
    """The id is resolved client-side against the API, so the shell is static."""
    with TestClient(server.app) as client:
        r = client.get("/report/whatever")
        assert r.status_code == 200
        assert "Building your report" in r.text


def test_the_store_is_capped_so_it_cannot_grow_without_bound():
    server._REPORTS.clear()
    for i in range(server._REPORT_LIMIT + 10):
        server._store_report(f"id{i}", {"status": "ready"})
    assert len(server._REPORTS) == server._REPORT_LIMIT
    assert "id0" not in server._REPORTS          # oldest evicted
    assert f"id{server._REPORT_LIMIT + 9}" in server._REPORTS
    server._REPORTS.clear()


def test_the_topic_under_discussion_counts_as_reached():
    """state.topics_covered only counts topics the engine moved PAST, so the
    last topic of every interview would otherwise read as 'never reached'."""
    ev = build_evidence(_state(
        q("Tell me about a system.", Objective.OPEN, topic="system design"),
        a("I built a payments pipeline."),
        topics=["system design", "failure modes"],
    ))
    assert "system design" in ev.topics_covered
    note = coverage_note(ev)
    assert note and "failure modes" in note
    assert "system design" not in note.split("never reached:")[-1]

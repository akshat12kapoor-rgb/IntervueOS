"""The deterministic half of the interview: objective selection."""

from __future__ import annotations

import pytest

from interview import InterviewState, Objective, Turn, _is_thin, _is_vague


def state(**kw) -> InterviewState:
    kw.setdefault("topics", ["system design", "databases", "failure modes"])
    kw.setdefault("duration_s", 600.0)
    return InterviewState(**kw)


def test_opens_with_an_open_question():
    assert state().next_objective() is Objective.OPEN


def test_vague_group_answer_triggers_a_demand_for_specifics():
    s = state()
    s.apply_objective(Objective.OPEN)
    s.record(Turn("candidate", "We basically rebuilt it and our team handled things like that"))
    assert s.next_objective() is Objective.SPECIFICITY


def test_a_concrete_answer_is_not_treated_as_vague():
    # Same hedges, but anchored by a number and first-person ownership.
    assert not _is_vague("We rebuilt it and I cut p99 latency from 800ms to 120ms")


def test_depth_cap_forces_a_topic_change():
    s = state()
    s.apply_objective(Objective.OPEN)
    s.record(Turn("candidate", "x" * 200 + " " + " ".join(["word"] * 40)))
    for _ in range(s.max_depth_per_topic):
        s.apply_objective(Objective.PROBE)
    assert s.next_objective() is Objective.NEXT_TOPIC
    s.apply_objective(Objective.NEXT_TOPIC)
    assert s.current_topic == "databases"
    assert s.depth_in_topic == 0


def test_probe_and_challenge_alternate_so_the_interview_is_not_monotone():
    s = state()
    s.apply_objective(Objective.OPEN)                       # depth 1
    s.record(Turn("candidate", " ".join(["substantive"] * 40)))
    seen = []
    for _ in range(4):
        obj = s.next_objective()
        seen.append(obj)
        if obj is Objective.NEXT_TOPIC:
            break
        s.apply_objective(obj)
    assert Objective.PROBE in seen and Objective.CHALLENGE in seen


def test_wrap_up_when_time_is_nearly_gone():
    s = state(duration_s=600.0)
    s.started_at -= 560          # 40s remaining, below the 75s threshold
    assert s.next_objective() is Objective.WRAP_UP


def test_interview_reports_itself_over_past_duration():
    s = state(duration_s=10.0)
    s.started_at -= 11
    assert s.is_over
    assert s.remaining == 0.0


@pytest.mark.parametrize("text,thin", [
    ("Yes.", True),
    ("I don't know.", True),
    (" ".join(["word"] * 25), False),
])
def test_thin_answer_detection(text, thin):
    assert _is_thin(text) is thin

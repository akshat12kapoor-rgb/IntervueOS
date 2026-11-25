"""Post-interview assessment.

Split deliberately in two:

* `build_evidence` is **deterministic**. It pairs each interviewer question with
  the answer it drew and carries the objective the engine chose, the topic, how
  long the candidate spoke and whether they were interrupted. No model is
  involved, so this half cannot hallucinate and is fully unit-testable.
* `ReportProvider` then judges that record. The model never sees a raw blob of
  conversation and is never asked what the interviewer was testing — that is
  already known, which is the whole point of the objective/phrasing split in
  ADR-003 and `interview.py`.

The model is therefore constrained to the one judgement it is actually good at:
was this answer substantiated, and by what words.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Sequence

from interview import InterviewState, Objective, Turn

REPORT_SCHEMA_VERSION = "report_v1"

#: What the engine was testing, in words a candidate can read. The enum names
#: are internal; these are not.
OBJECTIVE_INTENT = {
    Objective.OPEN: "Open the topic and let you frame it yourself",
    Objective.PROBE: "Go one level deeper on what you had just said",
    Objective.CHALLENGE: "Push on an assumption, tradeoff or failure mode",
    Objective.SPECIFICITY: "Pin down what you specifically did, concretely",
    Objective.NEXT_TOPIC: "Move to a new topic",
    Objective.WRAP_UP: "Close the interview",
}

#: Objectives that are navigation, not examination — excluded from scoring.
_NON_PROBING = {Objective.NEXT_TOPIC, Objective.WRAP_UP}


@dataclass(frozen=True, slots=True)
class Exchange:
    """One question and the answer it drew. The unit the report is built from."""

    index: int
    topic: str
    objective: str
    intent: str
    question: str
    answer: str
    answer_words: int
    answer_seconds: float
    interrupted: bool
    answered: bool
    """False when the interview ended, or the candidate was cut off, before a
    reply arrived. Scoring an unanswered question would be unfair."""

    scored: bool
    """False for navigation turns and unanswered questions. "Sure." is the
    correct reply to "let's move on to X", and grading it as a 1 would punish
    the candidate for the engine changing topic."""


@dataclass(frozen=True, slots=True)
class Evidence:
    """Everything measurable about the interview, before any judgement."""

    role: str
    topics: list[str]
    topics_covered: list[str]
    duration_s: float
    exchanges: list[Exchange] = field(default_factory=list)

    @property
    def probing(self) -> list[Exchange]:
        return [e for e in self.exchanges if e.scored]

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "topics": self.topics,
            "topics_covered": self.topics_covered,
            "duration_s": self.duration_s,
            "exchanges": [asdict(e) for e in self.exchanges],
        }


def build_evidence(state: InterviewState) -> Evidence:
    """Pair questions with answers. Deterministic — no model, no network."""
    exchanges: list[Exchange] = []
    turns: Sequence[Turn] = state.turns

    for i, turn in enumerate(turns):
        if turn.speaker != "interviewer":
            continue
        # The candidate's reply is the next candidate turn, if one came.
        reply: Turn | None = None
        for later in turns[i + 1:]:
            if later.speaker == "candidate":
                reply = later
                break
            if later.speaker == "interviewer":
                # Two interviewer turns in a row: the first drew no answer.
                break

        objective = turn.objective.value if turn.objective else "open"
        intent = (
            OBJECTIVE_INTENT.get(turn.objective, "Ask about the role")
            if turn.objective
            else "Ask about the role"
        )
        text = reply.text if reply else ""
        exchanges.append(
            Exchange(
                index=len(exchanges) + 1,
                topic=turn.topic or "the role",
                objective=objective,
                intent=intent,
                question=turn.text,
                answer=text,
                answer_words=len(text.split()),
                answer_seconds=round(reply.duration, 1) if reply else 0.0,
                interrupted=bool(reply and reply.interrupted),
                answered=reply is not None and bool(text.strip()),
                scored=(
                    reply is not None
                    and bool(text.strip())
                    and turn.objective not in _NON_PROBING
                ),
            )
        )

    # `state.topics_covered` counts only topics the engine has moved PAST, so
    # the topic under discussion when time runs out is excluded — which would
    # make the last topic of every interview read as "never reached". For the
    # report, a topic that was actually asked about was reached.
    touched = {e.topic for e in exchanges if e.answered}
    covered = [t for t in state.topics if t in touched or t in state.topics_covered]

    return Evidence(
        role=state.role,
        topics=list(state.topics),
        topics_covered=covered,
        # Clamped: `elapsed` is a monotonic difference, so a caller that
        # seeds started_at from the wall clock yields a huge negative number.
        # Both the page and the assessor read this, and neither should be
        # handed a negative duration.
        duration_s=max(0.0, round(state.elapsed, 1)),
        exchanges=exchanges,
    )


def coverage_note(ev: Evidence) -> str | None:
    """A caveat the model is not asked to produce, because it is arithmetic.

    An interview that covered two of five topics in four minutes supports far
    less than one that ran the full set, and a report that stays quiet about
    that reads as more authoritative than it is.
    """
    answered = len(ev.probing)
    missed = [t for t in ev.topics if t not in ev.topics_covered]
    bits = []
    if answered < 4:
        bits.append(
            f"only {answered} substantive answer{'s' if answered != 1 else ''} were given"
        )
    if missed:
        bits.append("these topics were never reached: " + ", ".join(missed))
    if ev.duration_s < 240:
        bits.append(f"the interview ran {int(ev.duration_s // 60)} min")
    if not bits:
        return None
    return (
        "Read this assessment lightly — "
        + "; ".join(bits)
        + ". It describes what was said, not the full picture of the candidate."
    )

"""Deterministic interview state.

This module owns *what the interview is doing*: how much time is left, which
topics have been covered, how deep the current thread has gone, and therefore
what the objective of the next question should be. It contains no LLM calls.

The LLM is handed an objective and phrases it. It does not choose the objective.
That separation is the point (Principle 4) and it is what makes the interview
reproducible, time-bounded, and analysable afterwards.

This is the V1 seed of the adaptive engine described in PROJECT_PLAN Phase 2.
The heuristics here are deliberately simple and deliberately explicit.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class Objective(enum.Enum):
    """What the next interviewer turn is meant to accomplish."""

    OPEN = "open"
    """First question on a topic — broad, lets the candidate choose their framing."""

    PROBE = "probe"
    """Go one level deeper on what they just said."""

    CHALLENGE = "challenge"
    """Push on an assumption, a tradeoff, or a failure mode."""

    SPECIFICITY = "specificity"
    """The answer was vague or used 'we'. Demand the concrete individual detail."""

    NEXT_TOPIC = "next_topic"
    """This thread is exhausted or capped. Move to an uncovered topic."""

    WRAP_UP = "wrap_up"
    """Time is nearly gone. Close the interview."""


@dataclass(slots=True)
class Turn:
    speaker: str  # "interviewer" | "candidate"
    text: str
    topic: str | None = None
    objective: Objective | None = None
    started_at: float = 0.0
    ended_at: float = 0.0
    interrupted: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.ended_at - self.started_at)


@dataclass(slots=True)
class InterviewState:
    """Compact structured state. Deliberately *not* the raw transcript — the
    transcript is kept separately and only a recent window is ever sent to the
    LLM (see `SessionConfig.transcript_window`)."""

    topics: list[str]
    duration_s: float
    role: str = "the role"
    started_at: float = field(default_factory=time.monotonic)

    turns: list[Turn] = field(default_factory=list)
    topic_index: int = 0
    depth_in_topic: int = 0
    max_depth_per_topic: int = 3
    wrap_up_threshold_s: float = 75.0
    _ended: bool = False

    # ---- time -----------------------------------------------------------

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def remaining(self) -> float:
        return max(0.0, self.duration_s - self.elapsed)

    @property
    def is_over(self) -> bool:
        return self._ended or self.remaining <= 0.0

    def mark_ended(self) -> None:
        self._ended = True

    # ---- topics ---------------------------------------------------------

    @property
    def current_topic(self) -> str:
        if self.topic_index >= len(self.topics):
            return self.topics[-1] if self.topics else "your background"
        return self.topics[self.topic_index]

    @property
    def topics_covered(self) -> list[str]:
        return self.topics[: self.topic_index]

    @property
    def topics_remaining(self) -> list[str]:
        return self.topics[self.topic_index :]

    def advance_topic(self) -> None:
        self.topic_index = min(self.topic_index + 1, len(self.topics))
        self.depth_in_topic = 0

    # ---- transcript -----------------------------------------------------

    def record(self, turn: Turn) -> None:
        self.turns.append(turn)

    @property
    def last_candidate_turn(self) -> Turn | None:
        for t in reversed(self.turns):
            if t.speaker == "candidate":
                return t
        return None

    def recent(self, n: int) -> list[tuple[str, str]]:
        return [(t.speaker, t.text) for t in self.turns[-n:]]

    # ---- the decision ---------------------------------------------------

    def next_objective(self) -> Objective:
        """Choose the objective for the next interviewer turn.

        Pure function of state. No model call. Easy to unit-test, which is
        exactly why it lives here.
        """
        if self.is_over:
            return Objective.WRAP_UP
        if self.remaining <= self.wrap_up_threshold_s:
            return Objective.WRAP_UP

        last = self.last_candidate_turn
        if last is None:
            return Objective.OPEN

        if self.depth_in_topic >= self.max_depth_per_topic:
            return Objective.NEXT_TOPIC


        if _is_vague(last.text):
            return Objective.SPECIFICITY

        if _is_thin(last.text):
            # Short, low-content answer — no thread worth pulling. Move on
            # rather than drilling into nothing.
            return Objective.NEXT_TOPIC if self.depth_in_topic >= 1 else Objective.PROBE

        # Alternate probing and challenging so the interview does not become a
        # single monotonous mode.
        return Objective.CHALLENGE if self.depth_in_topic % 2 == 1 else Objective.PROBE

    def apply_objective(self, objective: Objective) -> None:
        """Advance state to reflect that we just asked a question of this kind."""
        if objective is Objective.NEXT_TOPIC:
            self.advance_topic()
        elif objective is Objective.OPEN:
            self.depth_in_topic = 1
        elif objective is Objective.WRAP_UP:
            pass
        else:
            self.depth_in_topic += 1


_HEDGES = (
    "we ", "we'd", "we've", "we're", "our team", "the team",
    "kind of", "sort of", "basically", "stuff like that", "and so on",
    "things like that", "etc",
)


def _is_vague(text: str) -> bool:
    """Collective pronouns and hedging with no concrete anchor.

    Crude on purpose: this is a trigger for *asking a better question*, not a
    scoring judgement. A false positive costs one follow-up question, which is
    a thing real interviewers do anyway.
    """
    low = text.lower()
    hedge_hits = sum(1 for h in _HEDGES if h in low)
    has_concrete = any(ch.isdigit() for ch in text) or " i " in f" {low} "
    return hedge_hits >= 2 and not has_concrete


def _is_thin(text: str, min_words: int = 18) -> bool:
    return len(text.split()) < min_words

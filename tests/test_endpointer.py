"""The local endpointer's turn-taking rules, frame by frame.

These are the rules that replace Deepgram Flux's native turn detection, so they
are the part of ADR-009 most worth pinning down. Every test drives a stub
`SpeechGate` rather than `webrtcvad`, which makes the state machine
deterministic: a test that depended on a real VAD's opinion of synthetic noise
would be testing the VAD, not the hysteresis.
"""

from __future__ import annotations

import pytest

from providers._endpointer import Decision, Endpointer, SpeechGate

RATE = 16000
FRAME_MS = 20
FRAME_BYTES = int(RATE * FRAME_MS / 1000) * 2  # 640


class Script(SpeechGate):
    """Answers `is_speech` from a fixed list of booleans, one per frame."""

    def __init__(self, pattern: list[bool]) -> None:
        self.pattern = list(pattern)
        self.calls = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        assert len(frame) == FRAME_BYTES, "the endpointer must hand the VAD whole frames"
        assert sample_rate == RATE
        verdict = self.pattern[self.calls] if self.calls < len(self.pattern) else False
        self.calls += 1
        return verdict


def frames(n: int) -> bytes:
    return b"\x01\x00" * (FRAME_BYTES // 2 * n)


def build(pattern: list[bool], **kw) -> tuple[Endpointer, bytes]:
    """An endpointer wired to `pattern`, plus enough audio to exhaust it."""
    ep = Endpointer(
        sample_rate=RATE,
        frame_ms=FRAME_MS,
        gate=Script(pattern),
        start_ms=kw.pop("start_ms", 100),  # 5 frames
        end_silence_ms=kw.pop("end_silence_ms", 200),  # 10 frames
        preroll_ms=kw.pop("preroll_ms", 60),  # 3 frames
        **kw,
    )
    return ep, frames(len(pattern))


# ----------------------------------------------------------------------
# opening a turn
# ----------------------------------------------------------------------


def test_a_single_speech_frame_does_not_open_a_turn():
    """A keyboard click reads as speech for one frame. It is not a turn."""
    ep, audio = build([True] + [False] * 20)
    assert ep.feed(audio) == []
    assert not ep.in_speech


def test_start_requires_consecutive_speech_frames():
    """start_ms=100 at 20 ms frames means five in a row, not five in total."""
    ep, audio = build([True, False] * 6 + [True] * 5 + [False] * 4)
    out = ep.feed(audio)
    assert [b.decision for b in out] == [Decision.SPEECH_STARTED]
    assert ep.in_speech


def test_preroll_is_capped_and_does_not_grow_without_bound():
    """Pre-roll keeps the first consonant of the first word, but a long silence
    before the turn must not be uploaded along with it."""
    ep, audio = build([False] * 50 + [True] * 5 + [False] * 10, preroll_ms=60)
    ep.feed(audio[: FRAME_BYTES * 55])
    # 3 frames of pre-roll, never 50, however long the preceding silence was.
    assert ep.turn_bytes == FRAME_BYTES * 3
    assert ep.in_speech


# ----------------------------------------------------------------------
# closing a turn
# ----------------------------------------------------------------------


def test_a_short_pause_does_not_end_the_turn():
    """The thing a VAD cannot know: a mid-sentence breath is not a turn end.
    end_silence_ms=200 is 10 frames, so 5 frames of silence must not close it.
    """
    ep, audio = build([True] * 5 + [False] * 5 + [True] * 5 + [False] * 3)
    out = ep.feed(audio)
    assert [b.decision for b in out] == [Decision.SPEECH_STARTED]
    assert ep.in_speech, "a 100 ms pause must not end a turn"


def test_sustained_silence_ends_the_turn():
    ep, audio = build([True] * 10 + [False] * 12)
    out = ep.feed(audio)
    assert [b.decision for b in out] == [
        Decision.SPEECH_STARTED,
        Decision.SPEECH_ENDED,
    ]
    end = out[-1]
    assert end.audio, "the turn must carry its audio for transcription"
    assert end.speech_s == pytest.approx(len(end.audio) / 2 / RATE)
    assert not end.forced
    assert not ep.in_speech


def test_the_silence_counter_resets_on_speech():
    """Nine frames of silence, a word, then nine more must not close the turn,
    even though eighteen silent frames have gone by in total."""
    ep, audio = build([True] * 5 + [False] * 9 + [True] * 2 + [False] * 9)
    out = ep.feed(audio)
    assert [b.decision for b in out] == [Decision.SPEECH_STARTED]
    assert ep.in_speech


def test_a_second_turn_can_follow_the_first():
    ep, audio = build([True] * 6 + [False] * 12 + [True] * 6 + [False] * 12)
    out = ep.feed(audio)
    assert [b.decision for b in out] == [
        Decision.SPEECH_STARTED,
        Decision.SPEECH_ENDED,
        Decision.SPEECH_STARTED,
        Decision.SPEECH_ENDED,
    ]


# ----------------------------------------------------------------------
# framing and safety
# ----------------------------------------------------------------------


def test_audio_is_reframed_across_arbitrary_chunk_sizes():
    """The browser sends ~80 ms chunks, which need not divide into VAD frames.
    Feeding the same audio in odd-sized pieces must give the same result."""
    pattern = [True] * 10 + [False] * 12
    whole, audio = build(pattern)
    expected = [b.decision for b in whole.feed(audio)]

    piecemeal, audio2 = build(pattern)
    got: list[Decision] = []
    step = 237  # deliberately not a multiple of 640
    for i in range(0, len(audio2), step):
        got.extend(b.decision for b in piecemeal.feed(audio2[i : i + step]))
    assert got == expected


def test_a_monologue_is_cut_at_max_turn():
    """Whisper's upload ceiling is 25 MB. A candidate who never pauses must be
    cut rather than buffered until the request fails."""
    ep = Endpointer(
        sample_rate=RATE,
        frame_ms=FRAME_MS,
        gate=Script([True] * 500),
        start_ms=100,
        end_silence_ms=200,
        preroll_ms=20,
        max_turn_s=0.5,
    )
    out = ep.feed(frames(60))
    ends = [b for b in out if b.decision is Decision.SPEECH_ENDED]
    assert ends, "the turn must be forced closed"
    assert ends[0].forced is True
    assert ends[0].audio


def test_no_eager_events_are_ever_emitted():
    """ADR-009's explicit trade: a VAD has no semantic signal to speculate
    from, so the eager path is given up rather than approximated."""
    ep, audio = build([True] * 20 + [False] * 15)
    out = ep.feed(audio)
    assert {b.decision for b in out} <= {
        Decision.SPEECH_STARTED,
        Decision.SPEECH_ENDED,
    }


# ----------------------------------------------------------------------
# incremental audio for interim captions
# ----------------------------------------------------------------------


def test_take_increment_returns_only_new_audio():
    """Interims transcribe the increment, not the whole turn — that is what
    keeps the audio-seconds bill linear in speech rather than quadratic in turn
    length."""
    ep, audio = build([True] * 30)
    ep.feed(audio[: FRAME_BYTES * 10])
    first = ep.take_increment()
    assert first

    ep.feed(audio[FRAME_BYTES * 10 : FRAME_BYTES * 20])
    second = ep.take_increment()
    assert second
    assert len(second) == FRAME_BYTES * 10, "only the new audio, billed once"


def test_take_increment_is_empty_outside_a_turn():
    ep, audio = build([False] * 10)
    ep.feed(audio)
    assert ep.take_increment() == b""


def test_increment_resets_between_turns():
    ep, audio = build([True] * 6 + [False] * 12 + [True] * 6 + [False] * 12)
    ep.feed(audio)
    assert ep.take_increment() == b"", "a closed turn has no pending increment"


# ----------------------------------------------------------------------
# configuration guards
# ----------------------------------------------------------------------


@pytest.mark.parametrize("frame_ms", [15, 25, 40])
def test_webrtcvad_frame_sizes_are_enforced(frame_ms):
    with pytest.raises(ValueError, match="10, 20 or 30 ms"):
        Endpointer(frame_ms=frame_ms, gate=Script([]))


@pytest.mark.parametrize("rate", [22050, 24000, 44100])
def test_webrtcvad_sample_rates_are_enforced(rate):
    with pytest.raises(ValueError, match="8, 16, 32 or 48 kHz"):
        Endpointer(sample_rate=rate, gate=Script([]))

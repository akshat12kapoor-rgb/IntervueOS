"""The Groq audio providers, with the vendor client replaced.

No test here opens a socket. The `groq` SDK client is swapped for a fake on the
instance after construction, which is the narrowest seam that still exercises
the real request-shaping, WAV handling, barge-in and rate-limiting code.

What these tests are for: Orpheus and Whisper are *batch* APIs being worn as
streaming providers, and all the risk is in that adaptation — the 200-character
cap, the WAV round-trip, discarding audio for a question that was interrupted
while its request was in flight, and not letting interim captions starve the
end-of-turn transcription.
"""

from __future__ import annotations

import asyncio
import io
import wave

import pytest

from providers._audio import resample, split_for_synthesis, unwrap_wav, wrap_wav
from providers._endpointer import SpeechGate
from providers.base import TurnEvent
from providers.groq_tts import MAX_INPUT_CHARS, GroqOrpheusTts
from providers.groq_whisper import GroqWhisperStt, _RequestBudget

RATE = 16000
FRAME_BYTES = 640


def make_wav(seconds: float, rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x11\x00" * (int(seconds * rate) * channels))
    return buf.getvalue()


def frames(n: int) -> bytes:
    return b"\x01\x00" * (FRAME_BYTES // 2 * n)


# ======================================================================
# _audio
# ======================================================================


def test_wav_round_trips_without_touching_the_samples():
    pcm = b"\x01\x02" * 1000
    assert unwrap_wav(wrap_wav(pcm, 24000), 24000) == pcm


def test_a_vendor_sample_rate_we_did_not_ask_for_is_resampled():
    """Orpheus's returned sample rate is undocumented, so the provider reads it
    from the header rather than trusting what it requested."""
    out = unwrap_wav(make_wav(0.5, 48000), 24000)
    assert len(out) // 2 == pytest.approx(12000, rel=0.01)


def test_stereo_is_downmixed_to_mono():
    """session.py and the browser worklet both assume mono."""
    out = unwrap_wav(make_wav(0.1, 24000, channels=2), 24000)
    assert len(out) // 2 == pytest.approx(2400, rel=0.01)


def test_resampling_is_a_no_op_at_a_matching_rate():
    """The expected steady state: the provider asks for the rate it wants, so
    the interpolator should never actually run."""
    pcm = b"\x07\x00" * 500
    assert resample(pcm, 24000, 24000) is pcm


def test_non_pcm16_audio_is_rejected_loudly():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(24000)
        w.writeframes(b"\x40" * 100)
    with pytest.raises(ValueError, match="16-bit"):
        unwrap_wav(buf.getvalue(), 24000)


# ======================================================================
# splitting for Orpheus's 200-character cap
# ======================================================================


def test_short_text_is_not_split():
    assert split_for_synthesis("Why Postgres?", MAX_INPUT_CHARS) == ["Why Postgres?"]


def test_every_piece_respects_the_vendor_cap():
    text = (
        "So you moved from a single ledger table to append-only entries with a "
        "periodic rollup, and you said the hot row contention on the balance "
        "update was the bottleneck at about two thousand writes a second. What "
        "did you measure to land on that number, and what did you try first?"
    )
    pieces = split_for_synthesis(text, MAX_INPUT_CHARS)
    assert len(pieces) > 1
    assert all(len(p) <= MAX_INPUT_CHARS for p in pieces)


def test_splitting_never_cuts_inside_a_word():
    """A mid-word cut is audible as two separate utterances."""
    text = " ".join(["disestablishmentarianism"] * 20)
    for piece in split_for_synthesis(text, MAX_INPUT_CHARS):
        for word in piece.split():
            assert word == "disestablishmentarianism"


def test_an_unbreakable_token_is_hard_cut_rather_than_looping_forever():
    pieces = split_for_synthesis("x" * 700, 200)
    assert pieces
    assert all(len(p) <= 200 for p in pieces)
    assert "".join(pieces) == "x" * 700


def test_splitting_prefers_a_sentence_boundary():
    head = "A" * 150 + "."
    pieces = split_for_synthesis(head + " " + "B" * 120, MAX_INPUT_CHARS)
    assert pieces[0] == head


# ======================================================================
# fakes
# ======================================================================


class FakeBinaryResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self) -> bytes:
        return self._body


class FakeSpeech:
    def __init__(self, rate: int, delay: float = 0.0) -> None:
        self.rate = rate
        self.delay = delay
        self.inputs: list[str] = []

    async def create(self, *, model, voice, input, response_format):
        self.inputs.append(input)
        assert len(input) <= MAX_INPUT_CHARS, "the vendor cap must be honoured"
        assert response_format == "wav"
        if self.delay:
            await asyncio.sleep(self.delay)
        return FakeBinaryResponse(make_wav(0.05, self.rate))


class FakeTranscriptions:
    def __init__(self, text: str = "I built a payments service", delay: float = 0.0) -> None:
        self.text = text
        self.delay = delay
        self.calls: list[dict] = []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.delay:
            await asyncio.sleep(self.delay)
        return type("R", (), {"text": self.text})()


class FakeGroqClient:
    def __init__(self, speech=None, transcriptions=None) -> None:
        self.audio = type("A", (), {"speech": speech, "transcriptions": transcriptions})()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class AlwaysSpeech(SpeechGate):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return True


class NeverSpeech(SpeechGate):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return False


class Alternating(SpeechGate):
    """Speech for `speech_frames` frames, then silence forever."""

    def __init__(self, speech_frames: int) -> None:
        self.speech_frames = speech_frames
        self.n = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        self.n += 1
        return self.n <= self.speech_frames


# ======================================================================
# Orpheus TTS
# ======================================================================


def tts_with(speech: FakeSpeech, **kw) -> GroqOrpheusTts:
    tts = GroqOrpheusTts(api_key="test", sample_rate=24000, **kw)
    tts._client = FakeGroqClient(speech=speech)
    return tts


async def drain_audio(tts: GroqOrpheusTts, *, at_least: int, timeout: float = 2.0) -> bytes:
    """Pull audio until `at_least` bytes have arrived, or time out."""
    got = bytearray()

    async def pump():
        async for chunk in tts.audio():
            got.extend(chunk)
            if len(got) >= at_least:
                return

    try:
        await asyncio.wait_for(pump(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return bytes(got)


async def test_speak_produces_pcm_at_the_configured_rate():
    speech = FakeSpeech(rate=24000)
    async with tts_with(speech) as tts:
        await tts.speak("Why Postgres and not something else?")
        audio = await drain_audio(tts, at_least=1000)
    assert audio, "audio must reach the orchestrator"
    assert len(audio) % 2 == 0, "PCM16 frames are two bytes"
    assert speech.inputs == ["Why Postgres and not something else?"]


async def test_a_vendor_rate_mismatch_is_corrected_before_the_browser_sees_it():
    """The browser worklet plays at `tts_sample_rate`; wrong-rate audio would
    play at the wrong pitch rather than fail outright."""
    speech = FakeSpeech(rate=48000)
    async with tts_with(speech) as tts:
        await tts.speak("Hello.")
        audio = await drain_audio(tts, at_least=2000)
    # 0.05 s at 48 kHz downsampled to 24 kHz is ~1200 samples = ~2400 bytes.
    assert 2000 <= len(audio) <= 2600


async def test_long_text_is_split_into_several_vendor_requests():
    speech = FakeSpeech(rate=24000)
    long = "This is a sentence that runs on. " * 12
    async with tts_with(speech) as tts:
        await tts.speak(long)
        await drain_audio(tts, at_least=1)
        await asyncio.sleep(0.05)
    assert len(speech.inputs) > 1
    assert all(len(p) <= MAX_INPUT_CHARS for p in speech.inputs)


async def test_clear_discards_queued_text_so_an_interrupted_question_is_not_spoken():
    """Barge-in. The candidate has started talking; nothing further from the
    interrupted question may reach them."""
    speech = FakeSpeech(rate=24000, delay=0.05)
    async with tts_with(speech) as tts:
        await tts.speak("A" * 150 + ". " + "B" * 150 + ". " + "C" * 150 + ".")
        await tts.clear()
        await asyncio.sleep(0.2)
        issued = len(speech.inputs)
    assert issued <= 1, "queued pieces must be dropped, not synthesised"


async def test_clear_drops_audio_from_a_request_that_was_already_in_flight():
    """The race `clear()` exists for: a response arriving *after* the barge-in.
    Aura-2 needs a drop flag for the vendor's own buffer; here the equivalent is
    discarding our own late response."""
    speech = FakeSpeech(rate=24000, delay=0.1)
    async with tts_with(speech) as tts:
        await tts.speak("Tell me about the rollup.")
        await asyncio.sleep(0.02)  # request now in flight
        await tts.clear()
        leaked = await drain_audio(tts, at_least=1, timeout=0.4)
    assert leaked == b"", "audio synthesised for an interrupted turn must be dropped"


async def test_the_provider_keeps_working_after_a_barge_in():
    """A cleared provider must still be able to speak the *next* question."""
    speech = FakeSpeech(rate=24000)
    async with tts_with(speech) as tts:
        await tts.speak("First question.")
        await tts.clear()
        await tts.speak("Second question.")
        audio = await drain_audio(tts, at_least=500)
    assert audio
    assert "Second question." in speech.inputs


async def test_a_vendor_failure_does_not_kill_the_worker():
    """A 429 from the 10 RPM ceiling is expected, not exceptional. One failed
    sentence must not end the interview."""

    class Flaky(FakeSpeech):
        async def create(self, **kw):
            self.inputs.append(kw["input"])
            if len(self.inputs) == 1:
                raise RuntimeError("429 rate limit exceeded")
            return FakeBinaryResponse(make_wav(0.05, self.rate))

    speech = Flaky(rate=24000)
    async with tts_with(speech) as tts:
        await tts.speak("First.")
        await asyncio.sleep(0.05)
        await tts.speak("Second.")
        audio = await drain_audio(tts, at_least=500)
    assert audio, "the worker must survive a failed request"


async def test_empty_text_is_not_sent_to_the_vendor():
    speech = FakeSpeech(rate=24000)
    async with tts_with(speech) as tts:
        await tts.speak("   ")
        await tts.flush()
        await asyncio.sleep(0.05)
    assert speech.inputs == []


async def test_time_to_first_byte_is_recorded():
    """ADR-009 needs this number to compare against Aura-2's measured 334 ms."""
    speech = FakeSpeech(rate=24000, delay=0.05)
    async with tts_with(speech) as tts:
        await tts.speak("Why Postgres?")
        await drain_audio(tts, at_least=500)
    assert tts.metrics["ttfb_ms"], "time-to-first-byte must be measured, not assumed"
    assert tts.metrics["ttfb_ms"][0] >= 40


# ======================================================================
# Whisper STT
# ======================================================================


def stt_with(transcriptions, gate: SpeechGate, **kw) -> GroqWhisperStt:
    stt = GroqWhisperStt(
        api_key="test",
        sample_rate=RATE,
        gate=gate,
        start_ms=40,
        end_silence_ms=100,
        preroll_ms=20,
        **kw,
    )
    stt._client = FakeGroqClient(transcriptions=transcriptions)
    return stt


async def collect(stt: GroqWhisperStt, *, count: int, timeout: float = 2.0) -> list:
    got = []

    async def pump():
        async for ev in stt.events():
            got.append(ev)
            if len(got) >= count:
                return

    try:
        await asyncio.wait_for(pump(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return got


async def test_a_turn_becomes_start_of_turn_then_end_of_turn():
    """The two events a VAD can honestly synthesise."""
    tr = FakeTranscriptions("I built a payments service on Postgres")
    async with stt_with(tr, Alternating(speech_frames=10), interim_interval_s=0) as stt:
        pump = asyncio.create_task(collect(stt, count=2))
        await stt.send_audio(frames(30))
        events = await pump

    assert [e.event for e in events] == [TurnEvent.START_OF_TURN, TurnEvent.END_OF_TURN]
    assert events[1].transcript == "I built a payments service on Postgres"
    assert events[1].trigger == "vad_silence"


async def test_the_end_of_turn_transcript_is_one_request_over_the_whole_turn():
    """The transcript the orchestrator acts on must have full context — not be
    stitched together from interim fragments."""
    tr = FakeTranscriptions()
    async with stt_with(tr, Alternating(speech_frames=10), interim_interval_s=0) as stt:
        pump = asyncio.create_task(collect(stt, count=2))
        await stt.send_audio(frames(30))
        await pump

    assert len(tr.calls) == 1, "exactly one request per turn when interims are off"
    _name, body, mime = tr.calls[0]["file"]
    assert mime == "audio/wav"
    assert body[:4] == b"RIFF", "Whisper takes a file, so it must be a container"


async def test_the_term_hint_is_passed_as_whispers_prompt():
    """The measured win over Flux, whose `keyterm` is silently ignored."""
    tr = FakeTranscriptions()
    async with stt_with(
        tr,
        Alternating(speech_frames=10),
        interim_interval_s=0,
        prompt="PgBouncer, Redis, p99",
    ) as stt:
        pump = asyncio.create_task(collect(stt, count=2))
        await stt.send_audio(frames(30))
        await pump
    assert tr.calls[0]["prompt"] == "PgBouncer, Redis, p99"


async def test_no_eager_or_resumed_events_are_emitted():
    """ADR-009's declared trade, asserted so it cannot regress silently into a
    half-working speculation path."""
    tr = FakeTranscriptions()
    async with stt_with(tr, Alternating(speech_frames=10), interim_interval_s=0) as stt:
        pump = asyncio.create_task(collect(stt, count=2))
        await stt.send_audio(frames(40))
        events = await pump
    kinds = {e.event for e in events}
    assert TurnEvent.EAGER_END_OF_TURN not in kinds
    assert TurnEvent.TURN_RESUMED not in kinds


async def test_silence_alone_never_produces_a_turn():
    """The free-tier saving in COST_MODEL Note 1: a candidate sitting in silence
    must cost zero requests, where Flux billed the whole wall clock."""
    tr = FakeTranscriptions()
    async with stt_with(tr, NeverSpeech(), interim_interval_s=0) as stt:
        await stt.send_audio(frames(200))
    assert tr.calls == [], "silence must not be uploaded"


async def test_interim_updates_are_emitted_while_the_candidate_is_still_talking():
    tr = FakeTranscriptions("and then we sharded it")
    async with stt_with(
        tr, AlwaysSpeech(), interim_interval_s=0.01, min_interim_s=0.02
    ) as stt:
        pump = asyncio.create_task(collect(stt, count=2))
        for _ in range(3):
            await stt.send_audio(frames(10))
            await asyncio.sleep(0.05)
        events = await pump

    assert events[0].event is TurnEvent.START_OF_TURN
    assert any(e.event is TurnEvent.UPDATE for e in events)


async def test_interim_text_accumulates_rather_than_replacing():
    """Interims transcribe only the increment, so the caption has to be the
    concatenation — otherwise it would flicker back to a few words."""
    tr = FakeTranscriptions("chunk")
    updates: list[str] = []
    async with stt_with(
        tr, AlwaysSpeech(), interim_interval_s=0.01, min_interim_s=0.02
    ) as stt:

        async def pump():
            async for ev in stt.events():
                if ev.event is TurnEvent.UPDATE:
                    updates.append(ev.transcript)
                    if len(updates) >= 2:
                        return

        task = asyncio.create_task(pump())
        for _ in range(8):
            await stt.send_audio(frames(10))
            await asyncio.sleep(0.04)
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()

    assert len(updates) >= 2
    assert updates[1].startswith(updates[0]), "the caption must only grow"


async def test_interims_are_skipped_rather_than_queued_when_the_budget_is_spent():
    """A late caption is worthless, and starving the end-of-turn request to
    deliver one would be strictly worse."""
    tr = FakeTranscriptions()
    async with stt_with(
        tr,
        AlwaysSpeech(),
        interim_interval_s=0.01,
        min_interim_s=0.02,
        requests_per_minute=4,
        reserve_requests=4,  # zero headroom for captions
    ) as stt:
        for _ in range(5):
            await stt.send_audio(frames(10))
            await asyncio.sleep(0.03)

    assert tr.calls == [], "no interim may be issued with the reserve exhausted"
    assert stt.metrics["interims_skipped"], "and the skip must be recorded, not hidden"


async def test_an_end_of_turn_request_still_goes_through_when_captions_are_starved():
    """The reserve exists for exactly this: the transcript that matters wins."""
    tr = FakeTranscriptions("the part that matters")
    async with stt_with(
        tr,
        Alternating(speech_frames=10),
        interim_interval_s=0.01,
        min_interim_s=0.02,
        requests_per_minute=4,
        reserve_requests=4,
    ) as stt:
        pump = asyncio.create_task(collect(stt, count=2))
        await stt.send_audio(frames(30))
        events = await pump

    assert events[-1].event is TurnEvent.END_OF_TURN
    assert events[-1].transcript == "the part that matters"


async def test_a_transcription_failure_yields_an_empty_turn_not_a_crash():
    """session.py treats an empty END_OF_TURN as noise and does not burn an
    interviewer turn on it, which is the right fallback."""

    class Broken(FakeTranscriptions):
        async def create(self, **kw):
            raise RuntimeError("503 service unavailable")

    async with stt_with(
        Broken(), Alternating(speech_frames=10), interim_interval_s=0
    ) as stt:
        pump = asyncio.create_task(collect(stt, count=2))
        await stt.send_audio(frames(30))
        events = await pump

    assert events[-1].event is TurnEvent.END_OF_TURN
    assert events[-1].transcript == ""


async def test_speech_seconds_are_recorded_for_the_audio_seconds_budget():
    tr = FakeTranscriptions()
    async with stt_with(tr, Alternating(speech_frames=10), interim_interval_s=0) as stt:
        pump = asyncio.create_task(collect(stt, count=2))
        await stt.send_audio(frames(30))
        await pump
    assert stt.metrics["speech_seconds"]
    assert stt.metrics["speech_seconds"][0] > 0


async def test_events_stop_when_the_provider_closes():
    """`session.py` iterates `events()` until the stream ends; a generator that
    never finished would hang teardown."""
    tr = FakeTranscriptions()
    stt = stt_with(tr, AlwaysSpeech(), interim_interval_s=0)
    async with stt:
        pass
    got = [ev async for ev in stt.events()]
    assert got == []


# ======================================================================
# _RequestBudget
# ======================================================================


def test_the_reserve_is_only_available_to_privileged_requests():
    budget = _RequestBudget(per_minute=10, reserve=4)
    for _ in range(6):
        assert budget.allow(privileged=False)
        budget.charge()

    assert not budget.allow(privileged=False), "captions stop at the reserve"
    assert budget.allow(privileged=True), "end-of-turn requests may use the reserve"


def test_the_budget_window_slides():
    budget = _RequestBudget(per_minute=2, reserve=0)
    budget.charge()
    budget.charge()
    assert not budget.allow(privileged=True)
    # Age the entries past the 60 s window rather than sleeping through it.
    budget._hits = type(budget._hits)(t - 61 for t in budget._hits)
    assert budget.allow(privileged=True)
    assert budget.used == 0

"""Audio plumbing shared by the Groq providers.

Groq's audio endpoints are file-in / file-out, while `session.py` speaks raw
little-endian PCM16 mono. These helpers are the conversion layer, and they are
pure stdlib on purpose: `numpy` would be a 20 MB dependency to do linear
interpolation and a RIFF header, and the prototype's whole premise is that it
runs with nothing but the venv (ADR-005).

The Deepgram providers need none of this — they negotiate `encoding=linear16`
on the wire and get PCM straight off the socket.
"""

from __future__ import annotations

import array
import io
import wave


def wrap_wav(pcm16: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM16 mono in a RIFF container.

    Groq's transcription endpoint takes a file, not a stream, so every request
    needs a header. `wav` is chosen over `flac` deliberately: the Groq docs
    recommend wav for lower latency and flac only for smaller uploads, and one
    turn of speech is a few hundred KB either way.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def unwrap_wav(payload: bytes, want_rate: int) -> bytes:
    """Decode a RIFF/WAV body to raw PCM16 mono at `want_rate`.

    Orpheus is documented as returning wav and nothing else, but the sample rate
    it returns is *not* documented, so the rate is read from the header rather
    than assumed. When it already matches, this is a header strip and a copy.
    """
    with wave.open(io.BytesIO(payload), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(
                f"expected 16-bit PCM from the TTS vendor, got "
                f"{w.getsampwidth() * 8}-bit"
            )
        channels = w.getnchannels()
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())

    if channels > 1:
        frames = _downmix(frames, channels)
    if rate != want_rate:
        frames = resample(frames, rate, want_rate)
    return frames


def _downmix(pcm16: bytes, channels: int) -> bytes:
    src = array.array("h")
    src.frombytes(pcm16)
    out = array.array("h", bytes(2 * (len(src) // channels)))
    for i in range(len(out)):
        base = i * channels
        out[i] = sum(src[base : base + channels]) // channels
    return out.tobytes()


def resample(pcm16: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear-interpolation resample of PCM16 mono.

    Linear interpolation is not a good resampler in general — it is a gentle
    low-pass with audible imaging on wideband material. It is adequate here for
    one reason: this path exists only as a fallback for when the vendor returns
    a rate we did not ask for. The provider requests the configured rate
    directly, so the expected steady state is that this function never runs. If
    it turns out to run on every turn, replace it rather than tune it.
    """
    if src_rate == dst_rate or not pcm16:
        return pcm16

    src = array.array("h")
    src.frombytes(pcm16)
    n_src = len(src)
    if n_src < 2:
        return pcm16

    n_dst = max(1, round(n_src * dst_rate / src_rate))
    out = array.array("h", bytes(2 * n_dst))
    step = (n_src - 1) / (n_dst - 1) if n_dst > 1 else 0.0

    for i in range(n_dst):
        pos = i * step
        lo = int(pos)
        hi = min(lo + 1, n_src - 1)
        frac = pos - lo
        out[i] = int(src[lo] + (src[hi] - src[lo]) * frac)
    return out.tobytes()


def split_for_synthesis(text: str, limit: int) -> list[str]:
    """Split `text` into pieces of at most `limit` characters.

    Orpheus caps `input` at 200 characters, which is shorter than a long
    interviewer sentence, so this is on the hot path rather than a guard.
    Splitting prefers a sentence end, then a clause end, then a word boundary —
    a mid-word cut would be audible as two separate utterances.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = _last_break(window, ". ", "! ", "? ")
        if cut < limit // 3:
            cut = _last_break(window, ", ", "; ", ": ")
        if cut < limit // 3:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit  # one unbroken token longer than the cap; hard-cut it
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return [p for p in pieces if p]


def _last_break(window: str, *seps: str) -> int:
    """Index just past the last occurrence of any `sep`, or -1."""
    best = -1
    for sep in seps:
        idx = window.rfind(sep)
        if idx > -1:
            best = max(best, idx + len(sep.rstrip()))
    return best

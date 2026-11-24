"""All tunables in one place. No model ID or vendor string appears anywhere else."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True, slots=True)
class Config:
    # --- credentials ---
    deepgram_api_key: str = field(default_factory=lambda: os.getenv("DEEPGRAM_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))

    # --- models (ADR-004) ---
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "groq"))
    """"groq" or "anthropic". Selects the in-loop interviewer backend."""

    stt_provider: str = field(default_factory=lambda: os.getenv("STT_PROVIDER", "deepgram"))
    """"deepgram" or "groq" (ADR-009).

    "deepgram" is Flux: native turn detection including the speculative
    `EagerEndOfTurn`, at ~$0.195 per 30-minute interview against a finite trial
    credit. "groq" is Whisper plus the local VAD in
    `providers/_endpointer.py`: free, but batch transcription with no eager
    event, so the orchestrator stops speculating. Defaults to "deepgram"
    because it is the measured-faster path; docs/LATENCY.md records what the
    switch costs."""

    tts_provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "deepgram"))
    """"deepgram" or "groq" (ADR-009).

    "groq" is Orpheus: free, but non-streaming, capped at 200 characters per
    request, and limited to ~10 requests/minute — which is the binding
    constraint on the whole free pipeline. See docs/COST_MODEL.md."""

    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "openai/gpt-oss-120b"))
    stt_model: str = field(default_factory=lambda: os.getenv("STT_MODEL", "flux-general-en"))
    tts_model: str = field(default_factory=lambda: os.getenv("TTS_MODEL", "aura-2-thalia-en"))

    groq_stt_model: str = field(
        default_factory=lambda: os.getenv("GROQ_STT_MODEL", "whisper-large-v3")
    )
    """`whisper-large-v3` over `-turbo` deliberately. Both are free and share
    the same rate limits, and large-v3 measured *lower* WER on exactly the
    technical terms this product mishears — 0.125 vs turbo's 0.438 unprompted —
    at ~320 ms for an 8-second turn against turbo's ~294 ms. Paying ~25 ms for
    a third of the word error rate is the right trade here."""

    groq_tts_model: str = field(
        default_factory=lambda: os.getenv("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english")
    )
    groq_tts_voice: str = field(default_factory=lambda: os.getenv("GROQ_TTS_VOICE", "autumn"))
    """One of: autumn, diana, hannah (F); austin, daniel, troy (M)."""

    # --- audio ---
    stt_sample_rate: int = field(default_factory=lambda: _i("STT_SAMPLE_RATE", 16000))
    tts_sample_rate: int = field(default_factory=lambda: _i("TTS_SAMPLE_RATE", 24000))

    # --- turn taking, local VAD (STT_PROVIDER=groq only, ADR-009) ---
    vad_end_silence_ms: int = field(default_factory=lambda: _i("VAD_END_SILENCE_MS", 700))
    """Silence that ends a turn. This *is* the end-of-turn latency budget:
    unlike Flux's confidence threshold there is nothing clever to do, so the
    number is the lag. Below ~500 ms an ordinary mid-sentence pause starts
    cutting the candidate off."""

    vad_start_ms: int = field(default_factory=lambda: _i("VAD_START_MS", 100))
    """Speech needed to open a turn. Guards against clicks and coughs."""

    vad_preroll_ms: int = field(default_factory=lambda: _i("VAD_PREROLL_MS", 300))
    """Audio kept from *before* the trigger, so Whisper sees the first
    consonant of the first word rather than starting `vad_start_ms` late."""

    vad_aggressiveness: int = field(default_factory=lambda: _i("VAD_AGGRESSIVENESS", 2))
    """webrtcvad 0-3; higher filters more non-speech. 3 clips quiet sentence
    openings on laptop microphones."""

    stt_interim_interval_s: float = field(
        default_factory=lambda: _f("STT_INTERIM_INTERVAL_S", 4.0)
    )
    """How often to transcribe an incremental chunk for the live caption. Each
    one is a request against a 20 RPM ceiling shared with the end-of-turn
    transcriptions that actually matter, which is why this is seconds rather
    than milliseconds. 0 disables interim captions entirely."""

    stt_requests_per_minute: int = field(
        default_factory=lambda: _i("STT_REQUESTS_PER_MINUTE", 20)
    )
    stt_reserve_requests: int = field(default_factory=lambda: _i("STT_RESERVE_REQUESTS", 6))
    """Requests held back from interim captions so an end-of-turn request can
    always get through."""

    # --- turn taking (Deepgram Flux) ---
    eot_threshold: float = field(default_factory=lambda: _f("EOT_THRESHOLD", 0.5))
    """Confidence required to declare the turn over. 0.5-0.9.
    Measured 2026-09-11: 0.5 is ~235 ms faster than the 0.7 default with zero
    premature cutoffs across the sweep. See docs/LATENCY.md."""

    eager_eot_threshold: float = field(default_factory=lambda: _f("EAGER_EOT_THRESHOLD", 0.3))
    """Confidence required to *start drafting*. Lower = more speculation, more
    wasted tokens, lower latency when the guess lands. 0.3-0.9."""

    eot_timeout_ms: int = field(default_factory=lambda: _i("EOT_TIMEOUT_MS", 4000))
    """Silence that forces a turn to end even at low confidence."""

    # --- budget guards (COST_MODEL.md) ---
    max_interview_duration_s: int = field(default_factory=lambda: _i("MAX_INTERVIEW_DURATION_S", 600))
    max_generation_tokens: int = field(default_factory=lambda: _i("MAX_GENERATION_TOKENS", 160))
    max_response_chars: int = field(default_factory=lambda: _i("MAX_RESPONSE_CHARS", 400))
    transcript_window: int = field(default_factory=lambda: _i("TRANSCRIPT_WINDOW", 12))

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(
                "Missing required configuration: "
                + ", ".join(n.upper() for n in missing)
                + ". Copy .env.example to .env and fill it in."
            )


CONFIG = Config()

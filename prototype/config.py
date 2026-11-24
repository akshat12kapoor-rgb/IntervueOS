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

    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "openai/gpt-oss-120b"))
    stt_model: str = field(default_factory=lambda: os.getenv("STT_MODEL", "flux-general-en"))
    tts_model: str = field(default_factory=lambda: os.getenv("TTS_MODEL", "aura-2-thalia-en"))

    # --- audio ---
    stt_sample_rate: int = field(default_factory=lambda: _i("STT_SAMPLE_RATE", 16000))
    tts_sample_rate: int = field(default_factory=lambda: _i("TTS_SAMPLE_RATE", 24000))

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

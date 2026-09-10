# Cost Model

All figures are **usage-based**. Fixed infrastructure cost at V1 is $0 beyond a
free-tier Postgres and a hobby-tier host.

Prices verified 2026-09-10. Sources listed at the bottom. Re-verify quarterly —
`config.py` holds every model ID so a repricing is a config change.

## Unit: one 30-minute interview

Assumptions, stated so they can be argued with:
- Candidate speaks ~60% of wall-clock, interviewer ~30%, silence ~10%.
- STT stream stays open the entire 30 min (required for barge-in — we must hear
  the candidate *while* the interviewer is speaking).
- ~40 interviewer turns.
- Interviewer speaks ~150 wpm → ~9 min → ~1,350 words → ~7,400 characters.
- Stable cached prefix (system + JD + resume + rubric) ≈ 4,000 tokens.
- Per-turn fresh input (rolling state + recent transcript) ≈ 1,500 tokens.
- Per-turn output ≈ 80 tokens (a spoken question is short).

| Component | Model / rate | Quantity | Cost |
|---|---|---|---|
| STT + turn detection | Deepgram Flux `flux-general-en`, $0.0065/min | 30 min | **$0.195** |
| TTS | Deepgram Aura-2, $0.030/1K chars | 7,400 chars | **$0.222** |
| Interviewer loop — cached input | Sonnet 5 cache read, $0.20/MTok | 40 × 4,000 = 160K | $0.032 |
| Interviewer loop — fresh input | Sonnet 5 input, $2.00/MTok | 40 × 1,500 = 60K | $0.120 |
| Interviewer loop — output | Sonnet 5 output, $10.00/MTok | 40 × 80 = 3.2K | $0.032 |
| Cache write (once) | Sonnet 5 @ 1.25× input | 4K | $0.010 |
| **Voice loop subtotal** | | | **$0.611** |
| Post-interview autopsy — input | Opus 5, $5.00/MTok | ~15K | $0.075 |
| Post-interview autopsy — output | Opus 5, $25.00/MTok | ~6K | $0.150 |
| Document extraction (JD + resume) | Haiku 4.5, $1/$5 per MTok | 8K in / 2K out | $0.018 |
| Storage + egress | S3-compatible | negligible per session | ~$0.001 |
| **Total per 30-min interview** | | | **≈ $0.86** |

A 15-minute interview is roughly **$0.45**; a 60-minute one roughly **$1.65**
(the report cost grows sublinearly, the voice cost linearly).

## Comparison against the rejected option

| Approach | Voice loop / 30 min | + report | Total |
|---|---|---|---|
| **Cascaded (chosen)** | $0.61 | $0.25 | **$0.86** |
| OpenAI Realtime `gpt-realtime-2.1` | $1.80–$3.30 | $0.25 | $2.05–$3.55 |
| OpenAI Realtime mini | $0.60–$1.50 | $0.25 | $0.85–$1.75 |
| Gemini Live (3.1 Flash) | ~$0.69 | $0.25 | ~$0.94 |

The mini and Gemini tiers are cost-competitive, but neither gives up the
architectural control described in ADR-001, and both still require a separate
transcription pass to produce the answer-by-answer report. The cascaded
pipeline is cheapest *and* the right shape.

## What this implies commercially

At $0.86/interview, a "Pro" tier at $20/month supports ~23 interviews/month at
100% COGS and stays healthy at a 10-interview cap (~43% gross margin before
infra). A free tier of 1 interview/month costs $0.86 per signup — cheap
acquisition, but it **must** be metered, which is why `UsageRecord` and the
entitlement abstraction exist from day one rather than being retrofitted.

## Budget guards (implemented as config, enforced in code)

    MAX_INTERVIEW_COST_USD     hard stop; interview ends gracefully and still reports
    MAX_CONTEXT_TOKENS         caps the rolling state sent per turn
    MAX_GENERATION_TOKENS      caps a single spoken response
    MAX_INTERVIEW_DURATION_S   wall-clock ceiling, enforced by the state machine

The usage meter records estimated cost per session and per stage. Estimated vs
actual is reconciled from provider usage fields (`response.usage` for Claude,
byte/duration accounting for Deepgram) so the model above can be corrected with
real data rather than kept as a guess.

## Sources

- Deepgram Flux pricing & model: https://deepgram.com/pricing , https://developers.deepgram.com/docs/flux/quickstart
- Deepgram Aura-2 pricing: https://deepgram.com/learn/best-text-to-speech-apis-2026
- OpenAI Realtime pricing: https://hackernoon.com/openai-realtime-api-pricing-in-2026-real-world-data-from-4000-measured-sessions
- Gemini Live pricing: https://ai.google.dev/gemini-api/docs/pricing
- Claude model pricing: bundled `claude-api` skill model table (cached 2026-06-24)

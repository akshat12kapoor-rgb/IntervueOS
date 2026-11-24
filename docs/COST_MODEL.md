# Cost Model

> **Measurement status (2026-11-24).** The Deepgram half is measured against the
> live API. The interviewer loop moved to Groq's free tier (ADR-008), so its
> **dollar cost is now $0** and the Sonnet rows below are retained only as the
> paid-tier fallback, still unvalidated. The post-interview report rows remain
> estimated. Nothing below is fabricated; unmeasured rows say so.
>
> **The binding constraint on the free tier is rate limits, not dollars.** See
> the free-tier section immediately below.

All figures are **usage-based**. Fixed infrastructure cost at V1 is $0 beyond a
free-tier Postgres and a hobby-tier host.

Prices verified 2026-09-10. Sources listed at the bottom. Re-verify quarterly —
`config.py` holds every model ID so a repricing is a config change.

## Free-tier operating point (current, ADR-008)

The interviewer loop runs on Groq's free tier at **$0**. What replaces cost as
the constraint is throughput:

| Resource | Free-tier limit | What a 30-min interview needs | Headroom |
|---|---|---|---|
| Requests/min | ~30 RPM | ~1.3 turns/min (40 turns / 30 min) | ample |
| Requests/day | ~1,000 RPD | ~40 | ~25 interviews/day |
| Tokens/min | ~8,000 TPM | ~630 in + ~40 out per turn, ~1.3 turns/min ≈ **~870 TPM** | ~9x |

Measured per-turn input is **~630 tokens**, not the 4,000 assumed below — the
JD and resume in the smoke test were short. A real JD + resume will push the
prefix toward 4K, and because there is **no prompt caching on Groq** that full
prefix is re-sent every turn: ~4,000 × 1.3 ≈ **5,200 TPM**, which is ~65% of the
8,000 TPM ceiling. That is the number to watch. Mitigations, in order of
preference: trim the system prompt, truncate JD/resume harder than the current
20,000-char cap, or shrink `TRANSCRIPT_WINDOW`.

Free-tier limits are published per-model and have been cut at least twice in
2026, so re-verify at https://console.groq.com/docs/rate-limits rather than
trusting this table.

**What is still not free:** Deepgram STT + TTS (~$0.375 per 30-min interview,
against a finite $200 of trial credit) and the post-interview report. Groq hosts
`whisper-large-v3-turbo` and `canopylabs/orpheus-v1-english` on the same free
key, which is a plausible path to a fully-free pipeline — but Flux's native
turn detection would have to be replaced with a local endpointer, which is real
work and is not done.

## Unit: one 30-minute interview (paid-tier fallback)

Assumptions, stated so they can be argued with:
- Candidate speaks ~60% of wall-clock, interviewer ~30%, silence ~10%.
- STT stream stays open the entire 30 min (required for barge-in — we must hear
  the candidate *while* the interviewer is speaking).
- ~40 interviewer turns.
- Interviewer speaks ~150 wpm → ~9 min → ~1,350 words → ~7,400 characters.
- Stable cached prefix (system + JD + resume + rubric) ≈ 4,000 tokens.
- Per-turn fresh input (rolling state + recent transcript) ≈ 1,500 tokens.
- Per-turn output ≈ 80 tokens (a spoken question is short).

| Component | Model / rate | Quantity | Cost | Basis |
|---|---|---|---|---|
| STT + turn detection | Deepgram Flux `flux-general-en`, $0.0065/min | 30 min | **$0.195** | **confirmed** — see note 1 |
| TTS | Deepgram Aura-2, $0.030/1K chars | ~6,000 chars | **$0.180** | list price verified; volume still estimated |
| Interviewer loop — cached input | Sonnet 5 cache read, $0.20/MTok | 40 × 4,000 = 160K | $0.032 | **estimated** |
| Interviewer loop — fresh input | Sonnet 5 input, $2.00/MTok | 40 × 1,500 = 60K | $0.120 | **estimated** |
| Interviewer loop — output | Sonnet 5 output, $10.00/MTok | 40 × 80 = 3.2K | $0.032 | **estimated** |
| Cache write (once) | Sonnet 5 @ 1.25× input | 4K | $0.010 | **estimated** |
| **Voice loop subtotal** | | | **$0.569** | |
| Post-interview autopsy — input | Opus 5, $5.00/MTok | ~15K | $0.075 | **estimated** |
| Post-interview autopsy — output | Opus 5, $25.00/MTok | ~6K | $0.150 | **estimated** |
| Document extraction (JD + resume) | Haiku 4.5, $1/$5 per MTok | 8K in / 2K out | $0.018 | **estimated** |
| Storage + egress | S3-compatible | negligible per session | ~$0.001 | estimated |
| **Total per 30-min interview** | | | **≈ $0.82** | ~30% measured |

A 15-minute interview is roughly **$0.43**; a 60-minute one roughly **$1.56**
(the report cost grows sublinearly, the voice cost linearly).

### Note 1 — the STT stream must run for the full wall clock

This was an assumption; it is now a measured constraint. Deepgram Flux drives its
silence timeout from *received audio*. A probe that simply stopped sending when
the candidate stopped talking never received an `EndOfTurn` at all — the turn
hung until the next utterance bled into it. The client must keep streaming
silence, so STT bills the entire interview duration, not just the talking parts.
There is no "pause the meter while the interviewer speaks" optimisation.

### Note 2 — barge-in waste is real but negligible

Deepgram keeps synthesising ~0.92 s of speech after `Clear`. Aura bills per
character submitted, and the characters were committed at `Speak` time, so an
interruption wastes the unspoken remainder of that question — roughly 75
characters, about **$0.002**. Not worth engineering against.

### Actual spend on this validation run

Approximately **$0.18** of Deepgram credit across all probes (~8 minutes of
streamed audio, ~5,000 synthesised characters). Anthropic: **$0.00** — every
call was rejected for insufficient credit.

### Largest cost drivers, in order

1. **TTS characters (~31% of the voice loop).** Directly controlled by how long
   the interviewer talks. `MAX_RESPONSE_CHARS` is therefore a cost lever as well
   as a quality one — and short interviewer turns are what we want anyway.
2. **STT wall-clock (~34%).** Fixed by interview duration. Not reducible without
   shortening interviews.
3. **Claude input tokens (~27%, estimated).** The one with real headroom: prompt
   caching should move ~4K tokens/turn from $2.00 to $0.20 per MTok. **This is
   the single most important unverified number in the model** — if the cache is
   silently missing, the voice loop costs roughly 1.5x the figure above.

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

At $0.82/interview, a "Pro" tier at $20/month supports ~24 interviews/month at
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

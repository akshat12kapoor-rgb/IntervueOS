# Architecture

## Target system (Phase 1+)

    Next.js frontend  ──HTTPS──>  FastAPI modular monolith  ──>  Postgres
            │                              │                     S3-compatible
            └────WebSocket (audio)─────────┤                     object storage
                                           │
              ┌────────────────────────────┼──────────────────────────┐
              ▼                            ▼                          ▼
        Interview Engine            Document Engine              User Engine
        (state machine,             (parse, extract,             (auth, plans,
         objective selection,        structure JD/resume)         entitlements,
         scoring aggregation)                                     usage meter)
              │
              ▼
        Provider Layer  ──  SttProvider · TtsProvider · LlmProvider · StorageProvider

One deployable unit. Services get extracted only when a measurement says to —
the first candidate is the realtime voice loop, because it is the only part with
a fundamentally different scaling profile (long-lived connections vs. short
requests).

## The voice loop as built

    Browser                          Server                        Vendors
    ───────                          ──────                        ───────
    mic
     │ AudioWorklet, 80ms
     │ PCM16 @16kHz
     ├──── WS binary ──────────────> feed_audio ────────────────>  Deepgram Flux
     │                                                                 │
     │                                <──── SttEvent ───────────────────┘
     │                                       │
     │                                       ▼
     │                             InterviewSession (session.py)
     │                                       │
     │                        ┌──────────────┼───────────────┐
     │                        ▼              ▼               ▼
     │                  InterviewState   objective      barge-in /
     │                  (interview.py)   selection      cancellation
     │                                       │
     │                                       ▼
     │                                 LlmProvider ─────────────>  Claude
     │                                       │ fragments
     │                                       ▼ sentence at a time
     │                                 TtsProvider ─────────────>  Deepgram Aura-2
     │                                       │                          │
     │  <──── WS binary (PCM16 @24kHz) ──────┴──────────────────────────┘
     │  AudioWorklet ring buffer
    speaker

## The three timing paths that matter

**1. Normal turn.** `EndOfTurn` → generate → first sentence → TTS → first audio
byte. Every hop is streaming, so the candidate hears the first words of the
question while the rest is still being generated.

**2. Speculative turn.** `EagerEndOfTurn` fires several hundred ms before
`EndOfTurn`. Generation starts immediately and its fragments buffer in a queue.
If the final transcript matches what was drafted from, those buffered fragments
go straight to TTS — the LLM round trip has already happened. If it does not
match (or `TurnResumed` arrives), the draft is cancelled and discarded. The
`speculation_hit_rate` in the session summary reports how often the bet paid off.

**3. Barge-in.** `StartOfTurn` while the interviewer holds the floor cancels
three things in order: the generation task, the TTS vendor's buffer (`Clear`),
and the browser's playback queue (`{"type":"interrupt"}` → worklet flush).
Measured client-side flush latency: **11 ms**. All three are required — skipping
any one leaves the interviewer talking over the candidate.

## Why the orchestrator imports no vendor code

`session.py` depends only on the Protocols in `providers/base.py`. That is what
makes the turn-taking logic testable without network access or API keys — the
whole of `tests/test_voice_loop.py` runs against scripted providers in ~10
seconds — and it is what makes ADR-002/003/004 reversible.

`server.py` is the only module that names a vendor, and it only constructs them.

## Separation of concerns in the interview itself

| Decided by code (`interview.py`) | Decided by the model |
|---|---|
| How much time is left | How to phrase a question |
| Which topic is current | Which claim in an answer to pull on |
| Whether the thread is exhausted | What follow-up actually probes it |
| Whether an answer was vague or thin | Whether an answer was *correct* |
| When to wrap up | What the wrap-up sounds like |

The model never chooses the objective. It is handed one and phrases it. This is
what makes an interview reproducible, time-bounded, and analysable afterwards —
and it is why the post-interview report can say *what the interviewer was
testing* on every single question.

# Architecture Decision Record

Format: one decision per section. Status is one of `PROPOSED` (awaiting user
approval at a hard checkpoint), `ACCEPTED`, `SUPERSEDED`.

---

## ADR-001 — Cascaded voice pipeline, not a speech-to-speech model

**Status:** PROPOSED (hard checkpoint — recurring cost + vendor lock-in + core UX)

**Decision.** Build the voice loop as `streaming STT → application logic → LLM →
streaming TTS`, with each stage behind a provider interface. Do *not* use a
speech-to-speech realtime model (OpenAI Realtime, Gemini Live) as the core engine.

**Options considered.**

| | Cascaded (Flux + Claude + Aura-2) | Speech-to-speech (OpenAI Realtime) | Speech-to-speech (Gemini Live) |
|---|---|---|---|
| Cost / 30-min interview (voice only) | ~$0.40 | ~$1.80–$3.30 | ~$0.70 |
| Turn detection | Model-integrated (Flux), incl. speculative `EagerEndOfTurn` | Server VAD, generic | Server VAD, generic |
| App controls question selection / state | Yes, natively | Only via function calling — the model still drives | Same |
| Verbatim transcript for the autopsy report | Free, it *is* the pipeline | Separate transcription pass | Separate pass |
| Swap one stage | Yes | No — all-or-nothing | No |

**Why cascaded wins for *this* product specifically.**

1. **Principle 4 is the whole product.** The interview state machine — time
   budget, skill coverage, difficulty adaptation, contradiction detection,
   resume cross-examination — is deterministic application logic that decides
   *what to ask next*. A speech-to-speech model wants to own the conversation.
   Fighting that is harder than composing the pipeline ourselves.
2. **The transcript is a first-class artifact.** The interview autopsy is
   answer-by-answer. A cascaded pipeline produces word-level timings and
   confidences as a side effect — which is also where the objective
   communication metrics (WPM, pause duration, filler count) come from for free.
3. **Cost.** ~4–8× cheaper than OpenAI Realtime, and the expensive reasoning
   model is only invoked on *text*, once per turn, rather than being billed per
   second of audio.
4. **Turn-taking is better, not just cheaper.** Deepgram Flux integrates
   end-of-turn detection into the ASR model itself and emits `EagerEndOfTurn`
   (start drafting a response now) and `TurnResumed` (cancel it, they're still
   talking). That is a strictly better primitive than VAD-plus-silence-timeout,
   and it directly buys the "responds quickly" requirement.

**Cost impact.** ~$0.60–$1.00 per 30-minute interview all-in (see COST_MODEL.md),
vs ~$2.00–$3.50 for the OpenAI Realtime equivalent. Zero fixed cost — all usage-based.

**Lock-in impact.** Low by construction. `SttProvider`, `LlmProvider`,
`TtsProvider` are Python Protocols; each vendor is one file. The pipeline shape
(stream in, events out, cancellable generation) is vendor-neutral.

**Rejected alternative — browser Web Speech API for STT.** Free, but Chrome-only,
no word timings, no confidence scores, no turn model, and it stops on silence in
ways we cannot tune. Not viable as the primary path. Retained as a documented
*fallback* only.

---

## ADR-002 — Deepgram Flux for STT + turn detection

**Status:** PROPOSED

**Decision.** `flux-general-en` over `wss://api.deepgram.com/v2/listen`.

Chosen over Deepgram Nova-3 + a separate turn detector (LiveKit `turn-detector`,
Pipecat `smart-turn`) because Flux folds endpointing into the ASR model: one
network hop, one vendor, no 135M-parameter model to host ourselves, and it is
*cheaper* than Nova-3 streaming ($0.0065/min vs $0.0077/min) while adding the
turn model. Self-hosting a turn detector would add GPU/CPU inference cost and
operational burden for a strictly worse latency profile at our scale.

**Reversible?** Yes. `SttProvider` exposes turn events as our own enum; a
Nova-3 + external-endpointer implementation would satisfy the same interface.

---

## ADR-003 — Deepgram Aura-2 for TTS in V1

**Status:** PROPOSED

**Decision.** Aura-2 streaming, ~$0.030/1K chars, ~90ms time-to-first-byte.

Cartesia Sonic is marginally faster (~40–90ms) and ElevenLabs Flash v2.5 is more
expressive, but both cost ~$0.05/1K chars. At V1 the deciding factor is that
Aura-2 shares a vendor and an API key with STT — one account, one bill, one
integration to debug — at 60% of the price. Voice *realism* is not the binding
constraint for an interviewer persona; latency and cost are.

**Revisit when:** user testing says the voice sounds robotic enough to break
immersion. `TtsProvider` makes this a one-file change.

---

## ADR-004 — Model routing: Sonnet 5 in the loop, Opus 5 for the report

**Status:** PROPOSED

| Task | Model | Why |
|---|---|---|
| Interviewer turn (in the voice loop) | `claude-sonnet-5`, thinking disabled | Latency-critical. Must return ~60 tokens fast. Thinking would add seconds. |
| Post-interview assessment / autopsy | `claude-opus-5`, adaptive thinking | Not latency-critical, quality-critical. This is the product's actual output. |
| Document extraction (JD, resume → structured) | `claude-haiku-4-5` | Mechanical extraction against a fixed schema. |

Model IDs live in `config.py`, never inline. Prompt caching is mandatory on the
interviewer loop: system prompt + JD + resume + rubric are a stable prefix across
every turn of a session, so they are cached and the per-turn marginal input is
only the rolling state.

---

## ADR-005 — Python-only prototype, no Node

**Status:** ACCEPTED (reversible, low stakes)

Node is not installed on this machine. The prototype is FastAPI serving one
static HTML file, so it runs with nothing but the venv. The production frontend
will be Next.js (per the target architecture) — this only affects the prototype.

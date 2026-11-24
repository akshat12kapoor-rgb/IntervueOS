# Architecture Decision Record

Format: one decision per section. Status is one of `PROPOSED` (awaiting user
approval at a hard checkpoint), `ACCEPTED`, `SUPERSEDED`.

---

## ADR-001 — Cascaded voice pipeline, not a speech-to-speech model

**Status:** ACCEPTED 2026-09-11. Voice transport validated against live providers;
the interviewer-behaviour half is still unvalidated (no Anthropic credit).

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

**Status:** ACCEPTED with a known weakness (see "Measured" below)

**Decision.** `flux-general-en` over `wss://api.deepgram.com/v2/listen`.

Chosen over Deepgram Nova-3 + a separate turn detector (LiveKit `turn-detector`,
Pipecat `smart-turn`) because Flux folds endpointing into the ASR model: one
network hop, one vendor, no 135M-parameter model to host ourselves, and it is
*cheaper* than Nova-3 streaming ($0.0065/min vs $0.0077/min) while adding the
turn model. Self-hosting a turn detector would add GPU/CPU inference cost and
operational burden for a strictly worse latency profile at our scale.

**Measured 2026-09-11** (synthetic candidate speech, 5 utterances, live API):

| | Result |
|---|---|
| End-of-turn fired exactly once per utterance | 5/5 |
| Ended on model confidence, not silence timeout | 5/5 (`trigger: "model"`, conf 0.72-0.79) |
| EagerEndOfTurn fired | 5/5 |
| Eager transcript matched the final transcript | 5/5 |
| `TurnResumed` fired correctly on a mid-answer pause | yes (hesitant case) |
| EOT lag after the candidate stops | median **1038 ms** (977-2188) |
| Eager lead before EOT | median **210 ms** |
| Word error rate | mean 0.079, worst 0.30 |

The turn model is the reason to pick Flux and it performs. Two caveats:

1. **The eager path buys less than hoped — ~210 ms, not the "hundreds of
   milliseconds" the marketing implies.** It is still worth having (it costs
   nothing when the guess is right, and 5/5 guesses were right) but it does not
   rescue the 1-second EOT lag on its own.
2. **Domain vocabulary is the weak spot, and `keyterm` does not work.** Flux
   accepts a `keyterm` query parameter without error and **silently ignores it** —
   an A/B over identical audio produced byte-identical transcripts. Observed
   errors: "sharded" -> "resorted", "Redis" -> "reddish", "p99" -> "p ninety nine".
   An interviewer that mishears the technology under discussion asks a nonsense
   follow-up, so this matters more here than the aggregate WER suggests. Nova-3
   *does* support keyterm boosting but has no turn model. See TODO for the fix
   options.

**Reversible?** Yes. `SttProvider` exposes turn events as our own enum; a
Nova-3 + external-endpointer implementation would satisfy the same interface.

---

## ADR-003 — Deepgram Aura-2 for TTS in V1

**Status:** ACCEPTED provisionally — latency is 3.7x the vendor's published figure

**Decision.** Aura-2 streaming, ~$0.030/1K chars, ~90ms time-to-first-byte.

Cartesia Sonic is marginally faster (~40–90ms) and ElevenLabs Flash v2.5 is more
expressive, but both cost ~$0.05/1K chars. At V1 the deciding factor is that
Aura-2 shares a vendor and an API key with STT — one account, one bill, one
integration to debug — at 60% of the price. Voice *realism* is not the binding
constraint for an interviewer persona; latency and cost are.

**Measured 2026-09-11** (live API, 6 utterances, mean 57 chars):

| | Result |
|---|---|
| Time to first audio byte, steady state on an open socket | median **334 ms** (329-336) |
| Same, first utterance on a fresh socket | 335 ms |
| Audio the vendor still sends after `Clear` | **296 ms / 0.92 s of speech** |
| `Cleared` acknowledgement | 319 ms |

Two conclusions.

**The 90 ms figure in ADR-003's original justification is wrong in practice.**
Measured TTFB is ~334 ms and it is *not* connection setup — a fresh socket and a
warm one are within 1 ms of each other, so this is synthesis latency. That is
the second-largest term in the response path after the EOT lag, and it makes the
Cartesia comparison (claimed 40-90 ms) worth actually running rather than
assuming Aura-2 wins on the cost-per-character argument alone.

**The client-side drop in `deepgram_aura.py` is load-bearing, not defensive
coding.** Deepgram keeps streaming ~0.92 s of already-synthesised speech after
`Clear`. Without the local drop flag the candidate would hear almost a full
second of the question they just interrupted. This was written on the assumption
it might matter; it does.

**Revisit when:** the Cartesia A/B runs, or user testing says the voice sounds
robotic enough to break immersion. `TtsProvider` makes this a one-file change.

---

## ADR-004 — Model routing: Sonnet 5 in the loop, Opus 5 for the report

**Status:** SUPERSEDED by ADR-008 for the in-loop turn. The Opus-for-the-report
and Haiku-for-extraction rows remain PROPOSED — UNVALIDATED.

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

**Status:** ACCEPTED, with a correction 2026-11-24 — Node v26 *is* now installed
on this machine, so the stated premise no longer holds. The decision stands
anyway: the prototype still requires nothing but the venv, which is the property
worth keeping. Node is now used only by `video/` (Remotion), which is
documentation and not part of the running system.

Node was not installed on this machine when this was written. The prototype is FastAPI serving one
static HTML file, so it runs with nothing but the venv. The production frontend
will be Next.js (per the target architecture) — this only affects the prototype.


---

## ADR-006 — Bundle a CA trust store rather than depend on the host's

**Status:** ACCEPTED 2026-09-11

The python.org macOS builds ship without a usable CA bundle, so every `wss://`
handshake failed with `CERTIFICATE_VERIFY_FAILED` until certificates were
installed out of band. Rather than make that a setup step in the README, the
providers build their TLS context from `certifi` (`providers/_tls.py`).

Verification is always on; this never disables certificate checking. The benefit
is that a laptop, a CI runner, and a slim container image all behave identically.

---

## ADR-008 — Groq for the in-loop interviewer turn

**Status:** ACCEPTED 2026-11-24, validated live.

The in-loop turn moves from `claude-sonnet-5` to Groq `openai/gpt-oss-120b`.

**Why.** Two reasons, in order of weight:

1. **Cost.** Groq's free tier runs the interviewer loop at $0. The Anthropic
   account has never had credit, so ADR-004's in-loop row was never validated
   against a billed call — it was an estimate that blocked the whole prototype.
2. **Latency.** Measured 2026-11-24: ~470 ms to first token, ~520 ms to a
   complete ~40-token question, over three objectives (`probe`, `challenge`,
   `specificity`). That is inside the budget in docs/LATENCY.md.

**What this costs us.**

- **No prompt caching.** The stable prefix (~4K tokens of role + topics + JD +
  resume) is re-sent every turn. On the free tier the binding constraint is
  tokens-per-minute, not dollars — see docs/COST_MODEL.md. This is the single
  biggest reason to revisit the choice if a paid tier is ever adopted.
- **Reasoning models need handling.** `gpt-oss-120b` rejects
  `reasoning_effort="none"` (only `low`/`medium`/`high`), so the provider pins
  `low` and sets `reasoning_format="hidden"`. Without the latter, a reasoning
  preamble would stream straight into the TTS provider and be spoken aloud.
  `include_reasoning` and `reasoning_format` are mutually exclusive on this API.
- **Usage reporting differs.** Groq returns usage on the final stream chunk under
  `x_groq.usage`; the installed SDK (1.7.0) does not accept OpenAI's
  `stream_options={"include_usage": True}`.

**Reversibility.** High, and deliberately so. `LLM_PROVIDER=anthropic` switches
back with no code change; both providers satisfy `LlmProvider` and the
construction site in `server.py` picks between them. The Anthropic provider is
kept, not deleted.

**Still open.** The post-interview assessment is unchanged and still routed to
Opus in ADR-004 — i.e. still unvalidated and still not free. That is the next
decision, not this one.

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

---

## ADR-009 — Groq Whisper + a local VAD as a selectable free STT/TTS path

**Status:**
- **STT — ACCEPTED 2026-11-24, validated live.** `whisper-large-v3` plus a local
  endpointer replaces Flux when `STT_PROVIDER=groq`.
- **TTS — REJECTED 2026-11-24.** Orpheus is not adopted. `providers/groq_tts.py`
  stays in the tree, wired and unit-tested, behind `TTS_PROVIDER=groq`, but
  `deepgram` remains the default and the recommendation.

**Decision.** Add `providers/groq_whisper.py` (`whisper-large-v3` plus a local
voice-activity endpointer) and `providers/groq_tts.py`
(`canopylabs/orpheus-v1-english`), selected by new `STT_PROVIDER` /
`TTS_PROVIDER` config switches. Keep both Deepgram providers in place, and keep
`deepgram` as the default for both.

**The recommended setup is `STT_PROVIDER=groq` with `TTS_PROVIDER=deepgram`** —
free, measured STT; Deepgram for the voice. Not all-Groq.

### Why Orpheus was rejected

Two independent reasons, and **the rate limit is the real one**. Read them in
this order, because the gate is the more visible problem and the less important
one.

**1. The rate limit makes it unusable, measurement or no measurement.** Orpheus
allows **10 RPM and 100 RPD** and caps `input` at 200 characters. The
interviewer speaks ~6,000-7,400 characters per interview, so at a 200-character
ceiling that is ~50-60 requests — **roughly one 30-minute interview per day,
with no margin for a retry.**

This is a product ceiling, not a tuning problem. The only levers are a smaller
`MAX_RESPONSE_CHARS` or a less talkative interviewer; both are wanted anyway and
neither changes the order of magnitude. A paid tier would lift it, but the entire
point of this ADR was to stop paying. **Even a perfect latency measurement would
not have changed this conclusion**, which is why the decision does not wait on
one.

**2. It could never be measured on this account.** Every request returns
`400 model_terms_required`. The terms were accepted on 2026-11-24 and the gate
did not lift: six requests over ~100 s all failed. Diagnostics from that run
locate the problem precisely —

| Check (same key, same run) | Result |
|---|---|
| `whisper-large-v3` transcription | OK — the key is live |
| both Canopy models in `models.list()` | `active: true` |
| `orpheus-v1-english` speech | `400 model_terms_required` (6/6) |
| `orpheus-arabic-saudi` speech | `400 model_terms_required` |

— so the gate covers the whole Canopy Labs family for this key's organisation,
rather than being propagation lag on one model or a problem with the key. The
likely cause is an acceptance on a different organisation than the key belongs
to, or one needing an org admin rather than a member. No substitute model or
vendor was tried: a green number from a different TTS says nothing about Orpheus.

So `GroqOrpheusTts` has **never made a successful live call**. There is no
time-to-first-byte figure, no confirmation that the returned WAV is really PCM16
mono at the configured rate, and no exercise of the `clear()` epoch counter
against real audio. All three are covered by `tools/probe_groq_audio.py` and
would print on the first successful call.

### What would have to change to revisit it

Not the gate alone — fixing the terms acceptance would only make measurement
possible, and the rate limit would still decide the question. Revisit if **any
of these** changes:

- **Groq raises Orpheus's limits**, or a paid tier becomes acceptable. ~100 RPD
  is the binding number; roughly 300+ RPD would make a 30-minute interview
  routine rather than a once-a-day event.
- **The 200-character `input` cap is lifted or streaming is added.** The cap
  drives the request count, and the lack of streaming means time-to-first-byte
  is the full synthesis time of the first sentence — it cannot beat Aura-2's
  measured 334 ms time-to-first-*frame* on the same text.
- **The interviewer gets much terser.** If `MAX_RESPONSE_CHARS` fell far enough
  that an interview fit in ~25-30 requests, 100 RPD would allow three or four
  interviews a day. That is a product change, not a config tweak.
- **Another free TTS appears on the key.** `playai-tts` is documented but not
  available on this account — a models-list probe returns only the two Orpheus
  and two Whisper models. There is currently no alternative to fall back to.

The provider is kept rather than deleted precisely so that a revisit is a
config change and a measurement, not a rewrite.

### Why this is worth doing at all

The product goal is that the prototype costs nothing to run. After ADR-008 moved
the LLM to Groq, Deepgram was the only paid component left, burning a finite
$200 trial credit at ~$0.375 per interview. Groq hosts credible STT and TTS
models on the key already in `.env`.

**The architecture was built for exactly this.** `session.py` imports only the
three Protocols in `providers/base.py`, so neither new provider required a
single change to the orchestrator. `base.py`'s `TurnEvent` docstring had already
anticipated this specific case — "a provider with no eager support simply never
emits EAGER_END_OF_TURN / TURN_RESUMED and the orchestrator degrades to
non-speculative generation" — and that is precisely what happened.

### The VAD: webrtcvad, not Silero

Whisper is batch transcription with no turn detection whatsoever, so the turn
events have to be synthesised locally. Both candidates work; the deciding
factors were dependency weight and startup behaviour.

| | `webrtcvad-wheels` (chosen) | Silero via `torch.hub` |
|---|---|---|
| Install size | **29 KB prebuilt wheel** | ~800 MB+ (torch) |
| Python 3.14 | **cp314 wheel published** | torch 2.15 available |
| First-run network | **none** | downloads the model from torch.hub |
| Input format | **PCM16 @ 16 kHz, 10/20/30 ms frames — our wire format exactly, no conversion** | float tensors, needs conversion |
| Cost per frame | microseconds, synchronous | ms-scale, wants a thread or batching |
| Accuracy, noisy / far-field | **worse — a GMM over spectral features** | clearly better |

`webrtcvad-wheels` rather than `webrtcvad` itself because upstream ships only a
source tarball needing a C toolchain, while the fork publishes prebuilt wheels
including cp314.

The deciding argument: this prototype has nine dependencies and runs with
nothing but the venv (ADR-005). Adding ~800 MB and a first-run model download to
get turn detection would be out of all proportion to the rest of the system, and
the download would be a network dependency at startup. Being
microseconds-per-frame and synchronous also matters — `_endpointer.py` runs
inline in `send_audio()` on the most latency-sensitive path in the system, and a
model wanting a thread hop could cost more latency than its accuracy saved.

**Silero is the upgrade path, and the seam for it exists.** `_endpointer.py`
defines a `SpeechGate` protocol with one method; `WebrtcGate` is one
implementation and `Endpointer(gate=...)` accepts any other, so a `SileroGate`
would not touch the turn-taking state machine. **Accuracy on real microphones in
real rooms is the most likely reason to need it**, because every measurement
here used clean synthetic speech — the easiest possible case for an
energy-and-spectrum gate.

### What was given up versus Flux's native turn detection

**1. Speculative generation, entirely.** `EAGER_END_OF_TURN` and `TURN_RESUMED`
are never emitted, and `server.py` sets `SessionConfig.speculate=False` when
`STT_PROVIDER=groq`.

This is a deliberate omission, not an oversight. Flux's eager event is a
*semantic* judgement — the model saying "that sounded like a complete thought".
A VAD has no such signal: at 300 ms of silence it knows strictly less than it
will at 700 ms, and nothing qualitatively different. Synthesising an eager event
from a shorter silence threshold would fire on every ordinary mid-sentence
breath, and each false fire costs a discarded draft *and* a `TURN_RESUMED` the
orchestrator has to unwind. A worse-than-nothing mechanism is worse than nothing.

Measured cost: the eager path bought a **210-270 ms** head start on generation
(8/8 utterances, never mis-fired). Losing it means paying the full ~470 ms LLM
time-to-first-token at end-of-turn.

**2. End-of-turn lag on long answers.** Measured medians, three runs each:

| Answer length | Groq (VAD 700 ms + Whisper) | Flux | Delta |
|---|---|---|---|
| 5.9 s | **1157 ms** | 1295 ms | **138 ms faster** |
| 15.8 s | **1603 ms** | 1295 ms | 308 ms slower |

The Whisper leg grows with answer length because the whole turn is transcribed in
one request, so the crossover is around an 8-second answer. **Net cost of the
swap including the lost speculation: ~130 ms on short answers, ~580 ms on long
ones** — which puts long answers past the 2-second mark PROJECT_PLAN calls
noticeably slow. Full figures in docs/LATENCY.md.

Worth noting what is *better* here: Flux's 1295 ms was shown to be structural and
untunable (its whole threshold range recovers only ~235 ms), whereas the 700 ms
is `VAD_END_SILENCE_MS` — a real lever.

**3. Word-level timings and end-of-turn confidence.** `SttEvent.words` is always
empty and `end_of_turn_confidence` always 0.0. Whisper's `verbose_json` could
supply segment timings, but nothing consumes them and asking for them costs
response size on the latency-critical path. `trigger` is still populated
(`vad_silence` or `max_turn`).

### What was gained

**1. `prompt` biasing actually works — the one unambiguous win.** The worst
quality finding of the Deepgram validation was that Flux mangles exactly the
technical terms an interview is about ("sharded" → "resorted", "Redis" →
"reddish"), and that its `keyterm` parameter is accepted and *silently ignored*.
Whisper's `prompt` measurably moves those words, fed a hint built from the
session's own role, topics and job description (`server._term_hint`):

| Case | WER |
|---|---|
| `turbo`, no prompt | 0.438 |
| `turbo` + prompt | 0.188 |
| `large-v3` + prompt | **0.125** |

**2. Silence stops being billable.** COST_MODEL Note 1 recorded as a measured
constraint that Flux drives its silence timeout from received audio, so the
client must stream silence for the full wall clock and STT bills all 30 minutes.
Endpointing locally inverts that: only speech is uploaded. A 15.79 s utterance
billed 16.52 audio-seconds, and pure silence produces zero requests.

**3. Barge-in becomes exact.** Aura-2 keeps sending ~0.92 s of
already-synthesised speech after `Clear`, which is why `deepgram_aura.py` needs a
local drop flag. `groq_tts.py` holds everything itself, so `clear()` bumps an
epoch and discards both queued text and any response that lands late.

**4. `whisper-large-v3` over `-turbo`.** Both are free with identical rate
limits, and large-v3 measured *lower* latency as well as a third of turbo's word
error rate in paired runs — inverting the vendor's own price/performance framing.
A free tier makes the cheap-model argument moot.

### The two design decisions inside the STT provider

Whisper is a batch API, so "how is audio chunked into requests" and "how do
interim transcripts exist at all" had to be answered from scratch.

**Chunking: a turn is the unit of transcription.** Not a fixed window — that
would cut mid-word with no way to recover context across calls, whereas a VAD
turn boundary is by construction a point where nobody is talking. One request
per turn over the whole turn's audio produces `END_OF_TURN`.

**Interims: incremental, and display-only.** Each interim transcribes only the
audio since the last one, and the caption is the concatenation. The alternative —
re-transcribing the whole turn every N seconds — is more accurate but quadratic
in turn length (a 20 s answer at a 2 s cadence is 110 audio-seconds), which would
exhaust the hourly audio allowance on a few long answers.

The accuracy loss is acceptable for a reason specific to this codebase:
**`session.py` never makes a decision on an `UPDATE` transcript.** It forwards it
to the browser as `transcript_partial` and nothing else; every transcript that
reaches the interview state machine or the LLM comes from `END_OF_TURN`, which is
always a single whole-turn request. A mangled word in a caption costs cosmetics.
**If interims ever become load-bearing, revisit this first.**

Interims are also rate-limited and *skipped* rather than queued when the budget
is tight (`_RequestBudget`, with `STT_RESERVE_REQUESTS` held back): a late caption
is worthless, and starving the end-of-turn request to deliver one would be
strictly worse.

### The recommended setup

    STT_PROVIDER=groq        # free, measured
    TTS_PROVIDER=deepgram    # Aura-2 keeps the voice

| Configuration | $ / 30-min interview | Interviews/day | Measured? |
|---|---|---|---|
| All Deepgram | $0.375 | credit-bound | yes |
| **Groq STT + Deepgram TTS** | **$0.180** | **~7** | **yes** |
| All Groq | $0.000 | ~1 | STT only |

This takes **52% off the Deepgram bill** — $0.195 of the $0.375 was STT — and
stretches the remaining trial credit from ~530 interviews to ~1,100. Everything
behind it is measured: the end-of-turn crossover at ~8 seconds, and the WER
improvement from Whisper's `prompt`. The last $0.180 is what all-Groq would
save, against a ceiling of about one interview a day.

### Reversibility

Total, and by config alone — the property ADR-008 established.

    STT_PROVIDER=deepgram    # back to Flux, speculation included
    TTS_PROVIDER=deepgram    # back to Aura-2

Both default to `deepgram`, so this ADR changes no behaviour until someone opts
in. The switches are independent, so STT and TTS move one at a time; the
transport suite is parametrised over all five sensible combinations with every
provider class patched, so no test reaches a live API. Nothing was deleted, and
`server.py` still holds the only construction site.

**Where the Deepgram-specific config now applies:** `EOT_THRESHOLD`,
`EAGER_EOT_THRESHOLD` and `EOT_TIMEOUT_MS` are read only when
`STT_PROVIDER=deepgram`; the `VAD_*` and `STT_INTERIM_*` settings only when it is
`groq`. Both sets stay in `config.py` and `.env.example`, labelled.

### Still open

- **The VAD has only ever met synthetic speech.** This is the biggest open risk
  in the accepted half, and it compounds: every number in this ADR came from
  clean `say`-generated audio, which is the easiest possible input for a VAD —
  and webrtcvad is weakest exactly where that input is unrepresentative, namely
  background noise and far-field microphones. A human in a noisy room is the
  real test and has not been run. `VAD_AGGRESSIVENESS` and `VAD_END_SILENCE_MS`
  are the first things to tune; `SileroGate` behind the existing `SpeechGate`
  seam is the fallback if tuning is not enough.
- **Orpheus is rejected, not deleted.** `TTS_PROVIDER=groq` still selects it and
  its unit tests still run, so a future revisit is a config change plus a
  measurement. See "What would have to change to revisit it".
- **`p99` is still transcribed as "page 99"** by Whisper and "p ninety nine" by
  Flux. Neither stack handles it; it stays in TODO.md.
- **The post-interview report is still Opus** and still not free (ADR-004).

---

## ADR-010 — The report is deterministic first, judged second

**Status:** ACCEPTED 2026-11-25, validated live.

The post-interview assessment is split in two, and the split is the decision.

`report.py` pairs each interviewer question with the answer it drew and carries
the objective the engine chose, the topic, how long the candidate spoke and
whether they were interrupted. **No model is involved**, so this half cannot
hallucinate, and it is unit-tested without network access.

Only the judgement goes to an LLM, and it receives that record rather than a
raw transcript. It is never asked what the interviewer was testing, because
that is already known — which is the payoff of the objective/phrasing split in
ADR-003 finally being collected.

**Why not Opus, as ADR-004 said.** That row was never validated; the Anthropic
account has no credit, and it is the reason this feature sat unbuilt while the
rest of the prototype worked. Groq runs it for nothing. This is the one place
in the codebase where high reasoning effort is correct — nobody is waiting
mid-conversation. Measured end to end: **~6 s**, ~1.4K in / ~2.8K out.

**What the structure buys, concretely.** Two defects showed up the first time a
real report was rendered in a browser, and both were fixable *because* the
record is structured:

- A `next_topic` turn was being graded. "Let's talk about how it failed." /
  "Sure." scored **1/5** — punishing the candidate for the interview's own
  structure. `Exchange.scored` now marks navigation turns and unanswered
  questions alike, and the assessor returns null for them.
- The assessor referred to the candidate in the third person and invented a
  gendered pronoun. It is now required to address them as "you", which it
  should have been doing regardless: they are the reader.

Neither was visible from a unit test or a provider-level call. Rendering the
page was the thing that found them.

**Constraints accepted.** Reports live in memory, capped at 50, lost on
restart — persistence is still open in docs/TODO.md and this does not pretend
otherwise. The second-person rule and the no-invented-quotes rule are prompt
constraints, not guarantees; `_validate` enforces shape, not truthfulness. A
failed assessment renders the transcript and the error rather than an empty
page, and the provider raises rather than returning a blank — a fabricated
report is worse than a missing one.

# Measured Latency

> **Two stacks are measured here.** Everything from "The response path" down to
> "Speech recognition quality" is the **Deepgram** stack (2026-09-11), which is
> still the default. The **Groq free-tier** stack (ADR-009) is measured in the
> final section. Read both before changing `STT_PROVIDER`.

All Deepgram figures from live provider calls on 2026-09-11. Candidate speech is
**synthetic** (Deepgram Aura, a second voice) streamed into Flux in real time at
80 ms/chunk, exactly as the browser does.

**What that means for these numbers.** The STT and turn-detection path is real —
real audio, real model, real events. But synthetic speech is cleanly
articulated, noise-free, and only as hesitant as the text we wrote. A human
trailing off, saying "uhh" for two seconds, or sitting in a noisy room will do
worse. **Treat every number here as a best case.**

## The response path, end to end

    candidate stops speaking
        │
        │  ── 1.0-1.5 s ─────────────►  EndOfTurn          MEASURED (median ~1.3 s, outlier 3.8 s)
        │       └── ~250 ms earlier: EagerEndOfTurn        MEASURED (median 210-270 ms lead)
        │           └── generation starts here
        │
        ├── LLM time to first token                        NOT MEASURED (no Anthropic credit)
        │
        ├── ── 334 ms ──────────────►  first TTS byte      MEASURED (median 334 ms, 329-336)
        │
        └── ── ~10 ms ──────────────►  first audible word  MEASURED (browser worklet)

**Projected total, candidate stops → first audible word:**

    EOT lag (1300) + max(0, LLM_TTFT − eager_lead 250) + TTS TTFB (334) + client (10)

| If LLM TTFT is | Projected total |
|---|---|
| 400 ms | ~1.79 s |
| 600 ms | ~1.99 s |
| 900 ms | ~2.29 s |

Outliers follow the EOT lag: a 3.8 s end-of-turn becomes a ~4.5 s silence.

For reference, gaps between human conversational turns average ~200 ms. Two
seconds is noticeably slow, though an interviewer pausing to think is not
*implausible*. Four seconds is not defensible.

## End-of-turn threshold sweep

Three utterances per configuration, live API.

| `eot_threshold` | `eager_eot_threshold` | Median EOT lag | Premature cutoffs | Mean WER | Eager lead |
|---|---|---|---|---|---|
| 0.7 (default) | 0.5 | 1530 ms | 0/3 | 0.087 | 198 ms |
| 0.6 | 0.4 | 1525 ms | 0/3 | 0.087 | 160 ms |
| **0.5** | **0.3** | **1295 ms** | 0/3 | 0.087 | 270 ms |
| 0.5 | off | 1266 ms | 0/3 | 0.087 | — |

**The EOT lag is structural, not a tuning problem.** Taking the threshold from
0.7 to 0.5 — the whole supported range — recovers about 235 ms. There were zero
premature cutoffs at any setting, so 0.5 is free to adopt, but it does not solve
the latency. Disabling the eager path changes EOT timing not at all, confirming
that eager only buys a head start on generation.

This is the most important negative result of the validation: **we cannot
configure our way to a fast turn.** If ~2 s proves too slow, the fix is a
different STT/turn stack, not a different threshold.

## Speculative generation

| | Result |
|---|---|
| EagerEndOfTurn fired | 8/8 utterances |
| Eager transcript matched the final transcript | 8/8 |
| `TurnResumed` fired on a genuine mid-answer pause | yes |
| Median head start on generation | 210-270 ms |

The mechanism works exactly as designed and never mis-fired. It is simply worth
less than hoped — ~250 ms, not the "hundreds of milliseconds" implied by the
vendor's framing. Keep it: it is free when correct, and it was correct every time.

**Waste:** one discarded draft per `TurnResumed`. At an estimated ~80 output
tokens that is ~$0.0008 per event — irrelevant next to the latency it buys.

## Barge-in

| | Result |
|---|---|
| Perceived silence after the candidate starts speaking | **effectively immediate** |
| Browser worklet flush | 11 ms (measured in-browser) |
| Audio Deepgram still sends after `Clear` | 296 ms / **0.92 s of speech** |
| `Cleared` acknowledgement | 319 ms |

The client-side drop flag in `deepgram_aura.py` is load-bearing. Deepgram
continues streaming nearly a second of already-synthesised speech after `Clear`;
without the local drop the candidate would hear the tail of the question they
just interrupted. This was written speculatively and the measurement justifies it.

## Speech recognition quality

Mean WER 0.079 across five utterances (range 0.00-0.30 depending on utterance
and run). The aggregate is fine. The *distribution* is the problem: errors
cluster on exactly the words an interview is about.

| Reference | Transcribed |
|---|---|
| sharded | "resorted" / "charted" |
| Redis | "reddish" |
| p99 | "p ninety nine" |
| PgBouncer | "RanPgBouncer" |
| payments service | "payment service" |

An interviewer that mishears the technology under discussion asks a follow-up
about something the candidate never said, which reads as incompetence rather
than as a transcription error.

**`keyterm` does not fix this.** Flux accepts the parameter and silently ignores
it: an A/B over identical audio produced byte-identical transcripts in all three
cases. Options are in TODO.md.

---

# Groq free-tier stack (ADR-009)

Measured 2026-11-24 via `tools/probe_groq_audio.py`, which drives the shipped
`GroqWhisperStt` / `GroqOrpheusTts` classes — not a reimplementation — against
the live API, streaming audio at 80 ms/chunk exactly as the browser does.

Same caveat as above, and more so: the input is a clean `say`-generated
recording, so the VAD has an easy job. A human in a noisy room will do worse,
and the VAD will do *disproportionately* worse than Flux did, because Flux had
a speech model's acoustic robustness and this has an energy-and-spectrum gate.

## End-of-turn lag

This is the headline number. It is measured from the last chunk containing
speech to the moment `END_OF_TURN` is yielded, so it includes **both** the VAD's
silence wait and the Whisper round trip — the candidate experiences them as one
silence. Three runs per case, `whisper-large-v3`, `VAD_END_SILENCE_MS=700`.

| Answer length | Runs (ms) | Median EOT lag | of which Whisper | vs Flux's 1295 ms |
|---|---|---|---|---|
| 5.9 s | 1262 / 1157 / 1034 | **1157 ms** | 421 ms | **138 ms faster** |
| 15.8 s | 1800 / 1603 / 1586 | **1603 ms** | 866 ms | 308 ms slower |

The structure is `700 ms VAD silence + Whisper round trip`, and the Whisper leg
grows with the length of the answer because the whole turn is transcribed in one
request. So this stack beats Flux on short answers and loses on long ones, and
the crossover is around an 8-second answer.

That is a more favourable result than expected, and it is worth being clear
about *why*: Flux's 1295 ms was shown to be structural and untunable (the
threshold sweep above recovers only ~235 ms across its whole range), whereas the
700 ms here is a config value. `VAD_END_SILENCE_MS` is a real lever in a way
`eot_threshold` never was — but it is a lever with teeth, since the silence is
the only evidence a VAD has.

## Model and prompt comparison

One run each, 15.8 s utterance.

| Model | `prompt` | EOT lag | Whisper leg |
|---|---|---|---|
| `whisper-large-v3` | yes | 1395 ms | 659 ms |
| `whisper-large-v3` | no | 1688 ms | 950 ms |
| `whisper-large-v3-turbo` | yes | 1581 ms | 843 ms |
| `whisper-large-v3-turbo` | no | 2317 ms | 1580 ms |

`large-v3` beat `-turbo` on latency in every paired run here, which inverts the
vendor's own price/performance framing — and since both are free with identical
rate limits, there is no reason to prefer turbo. `GROQ_STT_MODEL` defaults to
`large-v3`. The spread between runs is wide enough that the model ordering
should be re-checked before anyone leans on it.

## Speech recognition quality — the one clear win

Term-dense utterance, WER against reference, `prompt` carrying the role, topics
and a slice of the job description. The reference terms are exactly the ones
Flux mangles.

| Case | WER | Transcript of the hard terms |
|---|---|---|
| `turbo`, no prompt | 0.438 | "redisk hash", "PG Bouncer", "page 99" |
| `turbo` + prompt | 0.188 | "redis cash", **"PgBouncer"**, "page 99" |
| `large-v3` + prompt | **0.125** | **"Redis cache"**, **"PgBouncer"**, "page 99" |

**This is the thing Deepgram could not do.** Flux's `keyterm` is accepted and
silently ignored; Whisper's `prompt` measurably moves the words that matter,
from a hint built out of the session's own job description (`server._term_hint`).
`p99` survives as "page 99" in every case — Flux rendered it "p ninety nine", so
neither stack handles it and it stays in TODO.md.

## What losing speculation costs

`EAGER_END_OF_TURN` is never emitted (see `_endpointer.py` for why a VAD cannot
honestly produce it), so `server.py` sets `SessionConfig.speculate=False` and
the orchestrator pays the full LLM time-to-first-token at end-of-turn instead of
the measured **210-270 ms** head start. Taking the 270 ms best case:

    candidate stops → first audible word
      Deepgram:  1295 (EOT) + max(0, 470 − 270) + 334 (TTS) + 10  ≈ 1.84 s
      Groq STT:  1157 (EOT, short answer) + 470 + 334 + 10        ≈ 1.97 s
      Groq STT:  1603 (EOT, long answer)  + 470 + 334 + 10        ≈ 2.42 s

using the 470 ms Groq LLM time-to-first-token from ADR-008 and Aura-2's measured
334 ms TTS. **Net cost of the STT swap: ~130 ms on short answers, ~580 ms on
long ones.** The long-answer case crosses the 2-second mark that
docs/PROJECT_PLAN.md calls noticeably slow.

## Orpheus TTS — REJECTED, never measured

**No latency number for Groq TTS exists.** Every request returns:

    400 model_terms_required — The model `canopylabs/orpheus-v1-english`
    requires terms acceptance. Please have the org admin accept the terms at
    https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english

This is a one-time acceptance by the account owner in the Groq console, which is
not something this work could do on their behalf. `GroqOrpheusTts` is written,
unit-tested against a faked client, and wired into `server.py`; it has never
made a successful live call. **Orpheus is rejected in ADR-009 — there is no
latency number for it and there will not be one on this account.**

**Second attempt, 2026-11-24, after the terms were reported accepted: still
blocked.** Six requests over ~100 s all returned `model_terms_required`.
Diagnostics from the same run, which narrow down where the problem is not:

| Check (same key, same run) | Result |
|---|---|
| `whisper-large-v3` transcription | **OK** — the key is live and unexpired |
| `orpheus-v1-english` in `models.list()` | `active: true` |
| `orpheus-v1-english` speech call | `400 model_terms_required` (6/6) |
| `orpheus-arabic-saudi` speech call | `400 model_terms_required` |

So this is not propagation lag on a single model: the whole Canopy Labs family
is gated for this API key's organisation, while the key itself works for Groq's
other audio models in the same session. The likely causes are that the
acceptance landed on a different account or organisation than the one this key
belongs to, or that it needs an org **admin** rather than a member. Worth
checking that the key in `.env` belongs to the org where the terms were
accepted, at https://console.groq.com/settings/limits.

No workaround was attempted. Substituting another TTS model or vendor would
produce a green number that says nothing about Orpheus.

**Orpheus was rejected on 2026-11-24 without a latency measurement**, because
the measurement would not have changed the decision: 10 RPM / 100 RPD against
~50-60 requests per interview is roughly one interview per day whatever the
latency turns out to be. The gate stopped the measurement; the rate limit
decided the question. See ADR-009 for the full reasoning and for what would
have to change to revisit it.

What is known from the vendor docs rather than measurement, and why the number
is unlikely to be good:

* The response is **one complete WAV body** — no streaming. Aura-2's 334 ms is a
  time-to-*first-frame* while synthesis continues; Orpheus's equivalent is the
  full synthesis time of the first sentence, so it cannot beat Aura-2 on the
  same text and will be worse the longer the first sentence is.
* `input` caps at **200 characters**, so a 400-character response is 2-3
  sequential requests.
* **10 requests/minute.** At 2-3 requests per interviewer turn this is the
  binding constraint on the whole free pipeline, not latency. See
  docs/COST_MODEL.md.

To fill this section in, accept the model terms and run:

    .venv/bin/python tools/probe_groq_audio.py <16k-mono.wav>

## Recommended setup

    STT_PROVIDER=groq
    TTS_PROVIDER=deepgram

Measured basis, all of it above: **52% off the Deepgram bill** ($0.375 →
$0.180 per 30-minute interview), an end-of-turn **crossover at ~8 seconds** —
faster than Flux below it, slower above — and **WER 0.438 → 0.125** from
Whisper's `prompt` on the technical terms Flux mangles. The price is ~130 ms of
response latency on short answers and ~580 ms on long ones.

All-Groq is not recommended: Orpheus is rejected (above, and ADR-009).

**Carry this caveat with the numbers.** Every figure in this section came from
clean `say`-generated audio. That is the easiest possible input for a VAD, and
webrtcvad is weakest precisely where it is unrepresentative — background noise
and far-field microphones. The end-of-turn figures in particular should be
re-measured against a human in a real room before anyone treats them as the
operating characteristics of the product.

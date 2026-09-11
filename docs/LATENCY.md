# Measured Latency

All figures from live provider calls on 2026-09-11. Candidate speech is
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

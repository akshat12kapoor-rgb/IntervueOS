# TODO

Ordered by what unblocks the most.

## Blocking Phase 1

- [ ] **Fund the Anthropic account.** Key is valid and authenticates; the balance
      is zero, so every billed call 400s. This blocks the entire
      interview-intelligence evaluation, which is the more important half of
      Checkpoint 1.
- [ ] Run the 12 adversarial cases (docs/AI_EVALUATION.md) against live Claude.
- [ ] Measure LLM TTFT; fill the one gap in docs/LATENCY.md.
- [ ] Verify prompt caching engages — assert `cache_read_input_tokens > 0` from
      turn two. If it silently misses, voice-loop cost is ~1.5x the model.
- [ ] **Human voice test** (needs a person): headphones first, then laptop
      speakers, to get a real false-barge-in rate. Currently unknown, not zero.
- [ ] Judge `artifacts/sample_exchange.wav` — is this voice credible as an
      interviewer?

## Adopt now (measured, free)

- [ ] `EOT_THRESHOLD=0.5`, `EAGER_EOT_THRESHOLD=0.3` — saves ~235 ms with zero
      premature cutoffs across the sweep.

## Speech recognition accuracy on domain vocabulary

Flux mishears the exact words an interview is about, and `keyterm` is silently
ignored. In rough order of cost:

- [ ] Try the mid-stream `Configure` control message — the on-the-fly config
      announcement mentions keyterms, even though the query parameter does nothing.
- [ ] Cheap post-STT normalisation: a Haiku pass that repairs transcripts against
      the JD/resume vocabulary we already extract. Adds a hop to the latency budget.
- [ ] Evaluate Nova-3 + an external turn detector (LiveKit `turn-detector`).
      Nova-3 supports keyterm boosting but has no turn model, so this trades the
      thing Flux is best at for the thing it is worst at. Measure before moving.

## Latency, if ~2 s proves too slow

- [ ] Measured: threshold tuning cannot fix it (docs/LATENCY.md). Changing this
      means changing the stack.
- [ ] A/B Cartesia Sonic against Aura-2's measured 334 ms TTFB.
- [ ] Re-price OpenAI Realtime / Gemini Live now that the cascaded path has real
      numbers to compare against, rather than the estimates in ADR-001.

## Known gaps in the prototype

- [ ] **Interrupted-turn text is approximate.** When the candidate barges in,
      the recorded interviewer turn is what was sent to TTS, not what was
      actually heard — the vendor's buffer may hold audio that never played.
      Correcting this needs byte-level accounting from the TTS stream. It
      matters for the report ("the candidate answered a half-asked question"),
      not for the conversation.
- [ ] **No reconnect.** A dropped WebSocket ends the interview. Needs session
      resume against a persisted state.
- [ ] **No fallback path.** ADR-001 promises degradation to non-streaming
      STT→LLM→TTS if the realtime path fails; not implemented.
- [ ] **No usage metering yet.** `AnthropicInterviewerLlm.usage` collects token
      counts but nothing aggregates or enforces a budget against them.
- [ ] Nothing is persisted. No database at all yet.
- [ ] `_is_vague` / `_is_thin` are crude string heuristics. Fine as triggers for
      asking a better question; they must never feed a score.
- [ ] Safari is untested. The worklets were verified in Chromium only.
- [ ] No mobile layout.

## Phase 1

- [ ] Postgres schema + migrations for the entities in the master spec.
- [ ] Document ingestion: PDF/DOCX/TXT → validated → structured extraction.
- [ ] JD and candidate skill maps.
- [ ] Auth (**hard checkpoint** — privacy and lock-in).
- [ ] Persist transcripts and turn timings.
- [x] First real post-interview report. Groq assessor over a deterministic
      evidence record; see `report.py` and ADR-010. Held in memory, so
      persistence below is still the blocker for anything real.
- [ ] Usage meter + entitlement abstraction (before any user can run two interviews).

## Engineering hygiene

- [ ] Ruff + mypy in CI.
- [ ] GitHub Actions running the test suite.
- [ ] Structured logging with session IDs.
- [ ] Load the eval set from AI_EVALUATION.md and wire the regression gate.

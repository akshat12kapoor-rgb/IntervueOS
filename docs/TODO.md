# TODO

Ordered by what unblocks the most.

## Blocking

- [ ] **Add `DEEPGRAM_API_KEY` and `ANTHROPIC_API_KEY` and run a live 10-minute
      interview.** Everything below is speculative until this happens.
- [ ] Measure and record: end-to-end latency, speculation hit rate, false
      barge-in rate on laptop speakers vs headphones.
- [ ] Tune `EOT_THRESHOLD` / `EAGER_EOT_THRESHOLD` against the recording.

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
- [ ] First real post-interview report.
- [ ] Usage meter + entitlement abstraction (before any user can run two interviews).

## Engineering hygiene

- [ ] Ruff + mypy in CI.
- [ ] GitHub Actions running the test suite.
- [ ] Structured logging with session IDs.
- [ ] Load the eval set from AI_EVALUATION.md and wire the regression gate.

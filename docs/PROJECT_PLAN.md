# Project Plan

Updated 2026-09-11.

## Where this stands

**Phase 0: complete.**
**Checkpoint 1: voice transport VALIDATED against live providers. Interviewer
behaviour NOT validated — the Anthropic account has no credit.**

Verdict: **CONDITIONAL PASS.** The voice path works and its weaknesses are
measured and understood. Nothing is known about whether the interviewer behaves
like an interviewer, because zero Claude calls have succeeded. Phase 1 must not
start until Step 2 runs.

## What exists

    prototype/
      session.py            turn-taking, barge-in, speculative generation
      interview.py          deterministic interview state + objective selection
      prompts.py            versioned prompts, injection-fenced document blocks
      config.py             every model ID and tunable, from the environment
      server.py             FastAPI: one WebSocket, one static page
      providers/
        base.py             SttProvider / TtsProvider / LlmProvider Protocols
        deepgram_flux.py    STT + model-integrated turn detection
        deepgram_aura.py    streaming TTS with mid-utterance Clear
        anthropic_llm.py    Claude, thinking off, prompt-cached system prefix
        scripted.py         test doubles (never imported by the server)
      static/               UI + capture/playback AudioWorklets
    tests/                  30 tests, ~11s, no network or API keys required
    docs/                   this file + ARCHITECTURE, DECISIONS, COST_MODEL,
                            SECURITY, AI_EVALUATION, TODO

## What is verified

- **30/30 tests pass.** Turn-taking, barge-in, speculative generation, draft
  invalidation, empty-turn handling, time expiry, provider-failure recovery,
  and the real FastAPI WebSocket path with scripted providers.
- **The tests bite.** Three deliberate mutations — removing barge-in
  cancellation, accepting a mismatched speculative draft, removing the topic
  depth cap — each fail the suite. The first one initially did *not*, because
  session teardown cancelled the same tasks; the assertion was tightened to
  measure state at the instant of interrupt.
- **Browser audio path, measured in a real browser.** Both AudioWorklets load,
  playback is audible, the drain signal fires, and **flush-on-barge-in silences
  output in 11 ms** and recovers afterwards.
- **Server boots**; `/health`, `/`, and all static assets return 200; the
  WebSocket refuses cleanly and legibly when credentials are missing.

## Live validation, 2026-09-11

Deepgram: working. Full results in `docs/LATENCY.md`. Headlines:

- End-of-turn fired correctly 8/8, always on model confidence, never on timeout.
- Speculative generation fired 8/8 and matched the final transcript 8/8.
- EOT lag median ~1.3 s and **structurally untunable** — the full threshold
  range moves it 235 ms.
- TTS time-to-first-byte 334 ms, not the ~90 ms the vendor publishes.
- Barge-in is perceptually immediate; the vendor's 0.92 s post-`Clear` tail is
  absorbed by the client-side drop, which the measurement proved necessary.
- Projected total response latency ~1.8-2.0 s, pending the LLM term.
- STT mishears domain vocabulary ("Redis" -> "reddish", "sharded" -> "resorted")
  and Flux **silently ignores** `keyterm`.

## What is STILL NOT verified

**Anthropic has zero credit.** `models.list` succeeds, so the key is valid and
authenticated; every billed call returns HTTP 400 "credit balance is too low".
That blocks:

- **All of Step 2 — the entire interview-intelligence evaluation.** The 12
  adversarial cases have not been run. Nothing is known about whether the
  interviewer coaches, reveals answers, cross-examines, notices contradictions,
  or holds its persona.
- LLM time to first token — the one unmeasured term in the latency budget.
- Whether prompt caching actually engages. Flagged in COST_MODEL.md as the
  single most important unverified number: if the cache silently misses, the
  voice loop costs ~1.5x the modelled figure.
- Real interviewer response length, and therefore real TTS spend.

**Needs a human at a keyboard** (I cannot speak into a microphone):

- A real interview with a human voice — genuine disfluencies, background noise,
  trailing off mid-sentence. All STT and EOT numbers above are from synthetic
  speech and are a best case.
- The laptop-speaker echo test. Whether browser AEC prevents the interviewer's
  own voice triggering false barge-ins is **completely unmeasured**; the false
  barge-in rate is currently unknown, not zero.
- Perceived TTS quality. `artifacts/sample_exchange.wav` is provided for this.

## Phases

- **Phase 0 — Discovery & architecture.** Done.
- **Checkpoint 1 — Voice prototype.** Built; awaiting a live run.
- **Phase 1 — Vertical MVP.** JD + resume upload and extraction, persistence,
  full transcript, first real report.
- **Phase 2 — Adaptive interview.** Skill maps, resume cross-examination, JD
  coverage, contradiction detection, difficulty adaptation, personalities.
- **Phase 3 — Interview autopsy.** Multi-dimensional scoring with contextual
  weighting, answer-by-answer analysis, concept gaps, evidence-based report.
- **Phase 4 — Personalised practice.** Weakness-driven questions, study plans,
  skill graph, progress tracking.
- **Phase 5 — Polish.** Onboarding, errors, mobile, a11y, analytics, SEO, privacy controls.
- **Phase 6 — Production.** Deploy, secrets, backups, monitoring, rate limits, CI/CD.

## Immediate next steps

1. **Fund the Anthropic account.** Everything else is downstream.
2. Run Step 2 — the 12 adversarial interview-intelligence cases.
3. Measure LLM TTFT and confirm the prompt cache engages
   (`usage.cache_read_input_tokens` > 0 from turn two).
4. Human voice test with headphones, then with laptop speakers, to get a real
   false-barge-in rate.
5. Adopt `EOT_THRESHOLD=0.5` / `EAGER_EOT_THRESHOLD=0.3` — measured as free.
6. Only then decide on Phase 1.

If Step 2 shows the interviewer coaches, reveals answers, or cannot
cross-examine, that is a prompt and interview-engine problem and Phase 1 waits.
If total latency lands above ~2.5 s, ADR-002 needs revisiting — and the sweep
shows that means changing the stack, not the config.

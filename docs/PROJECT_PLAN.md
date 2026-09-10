# Project Plan

Updated 2026-09-10.

## Where this stands

**Phase 0 (discovery + architecture): complete.**
**Checkpoint 1 (voice prototype): built and tested, but not yet run live —
blocked on API keys.** See "What is not verified" below.

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

## What is NOT verified

**No live voice interview has been run.** There are no `DEEPGRAM_API_KEY` or
`ANTHROPIC_API_KEY` credentials in this environment, so every claim about
end-to-end latency, real turn-detection quality, and how natural the
conversation actually feels is **unmeasured**. The vendor providers are written
against the published protocols and have never exchanged a packet.

Specifically unverified:
- Real end-to-end latency (`EndOfTurn` → first audible word).
- Real speculation hit rate — the number that decides whether ADR-002's eager
  path is worth its wasted tokens.
- Whether browser echo cancellation is enough to prevent the interviewer's own
  voice triggering false barge-ins on laptop speakers.
- Whether Aura-2 sounds like a person a candidate would take seriously.
- Whether Claude at `max_tokens=160` with thinking off holds the interviewer
  persona (Principle 5) under pressure, or drifts into coaching.

Every one of those is answerable within an hour of getting keys.

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

1. Add the two API keys and run a live 10-minute interview (see README).
2. Record the measured numbers in COST_MODEL.md and this file — replace the
   estimates with observations.
3. Tune `EOT_THRESHOLD` / `EAGER_EOT_THRESHOLD` against the recording.
4. Only then start Phase 1.

Nothing in Phase 1 should be built before step 1 happens. If the voice loop
does not feel human, the architecture above is the thing that changes, and
everything built on top of it would be rework.

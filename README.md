# IntervueOS

Real-time adaptive AI interview simulator. A candidate uploads a job description
and a resume, has a voice interview with an AI interviewer that cross-examines
their answers, and gets an evidence-based breakdown afterwards.

The name is temporary and appears only in `prototype/static/index.html`,
`prototype/server.py`, and this file.

## Status

Phase 0 is complete and the **voice prototype is built and tested** — but it has
**not been run live**, because this environment has no provider API keys. See
`docs/PROJECT_PLAN.md` for exactly what is and is not verified.

## Running the prototype

Needs Python 3.12+ and two API keys:

- **Deepgram** — https://console.deepgram.com — one key covers both speech
  recognition (Flux) and speech synthesis (Aura-2). New accounts get $200 free
  credit, which is roughly 400 ten-minute interviews.
- **Anthropic** — https://console.anthropic.com

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in the two keys
cd prototype && ../.venv/bin/python -m uvicorn server:app --port 8000
```

Open http://127.0.0.1:8000, paste a job description and a resume, press Start.

**Use headphones.** Without them your speakers feed the interviewer's voice back
into your microphone and it reads as an interruption.

## Running the tests

```bash
.venv/bin/python -m pytest
```

30 tests, ~11 seconds, no network and no API keys needed — the vendor providers
are swapped for scripted doubles, so the turn-taking logic is tested
deterministically.

## Documentation

| File | What it covers |
|---|---|
| `docs/PROJECT_PLAN.md` | Status, what is verified, what is not, phases |
| `docs/ARCHITECTURE.md` | System design and the three timing paths |
| `docs/DECISIONS.md` | ADRs, with the options that were rejected and why |
| `docs/COST_MODEL.md` | ~$0.86 per 30-minute interview, itemised |
| `docs/SECURITY.md` | Threat model, prompt injection, privacy |
| `docs/AI_EVALUATION.md` | How the model's judgement gets checked |
| `docs/TODO.md` | Prioritised remaining work |

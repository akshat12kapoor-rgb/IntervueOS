# Runbook

How to run IntervueOS yourself, and what deploying it would take.

The companion video (`video/`) covers the same ground visually. This file exists
because you cannot copy a command out of a video.

---

## 1. Run it locally

### Prerequisites

- **Python 3.12+**. Node is *not* required to run the prototype (ADR-005).
- **Headphones.** Not a nicety: without them your speakers feed the
  interviewer's voice back into your microphone and barge-in fires constantly.
- **Two API keys**, both free to start:

| Key | Where | Cost |
|---|---|---|
| `GROQ_API_KEY` | https://console.groq.com/keys | Free tier, no card |
| `DEEPGRAM_API_KEY` | https://console.deepgram.com | $200 trial credit |

One Deepgram key covers both speech-to-text (Flux) and text-to-speech (Aura-2).

### Setup

```bash
git clone https://github.com/akshat12kapoor-rgb/IntervueOS
cd IntervueOS
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Then open `.env` and paste in the two keys. Everything else has a working
default.

### Start the server

```bash
cd prototype && ../.venv/bin/python -m uvicorn server:app --port 8000
```

Or, from the repo root, using the committed launch config's arguments:

```bash
.venv/bin/python -m uvicorn server:app --app-dir prototype --port 8000
```

Open http://127.0.0.1:8000, paste a job description and your resume, press
**Start interview**.

### Confirm it came up correctly

```bash
curl -s http://127.0.0.1:8000/health
```

```json
{"ok":true,"deepgram_key":true,"llm_provider":"groq","llm_key":true,
 "models":{"llm":"openai/gpt-oss-120b","stt":"flux-general-en","tts":"aura-2-thalia-en"}}
```

If `llm_key` or `deepgram_key` is `false`, `.env` was not picked up — check you
are running from a directory where `python-dotenv` can find it.

### Run the tests

```bash
.venv/bin/python -m pytest
```

33 tests, ~12 seconds, **no network and no API keys needed**. The vendor
providers are swapped for scripted doubles, so turn-taking is tested
deterministically. The transport suite is parametrised over both LLM backends,
so no test ever reaches a live API.

---

## 2. Configuration

Every tunable lives in `prototype/config.py`, read from `.env`. No model ID or
vendor string appears anywhere else in the codebase.

### Credentials and routing

| Variable | Default | Notes |
|---|---|---|
| `DEEPGRAM_API_KEY` | — | Required. STT + TTS. |
| `GROQ_API_KEY` | — | Required when `LLM_PROVIDER=groq`. |
| `ANTHROPIC_API_KEY` | — | Required only when `LLM_PROVIDER=anthropic`. |
| `LLM_PROVIDER` | `groq` | `groq` or `anthropic`. Switches backend, no code change. |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Also `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`. |
| `STT_MODEL` | `flux-general-en` | Deepgram Flux. |
| `TTS_MODEL` | `aura-2-thalia-en` | Deepgram Aura-2. |

To see which models your Groq key can actually reach:

```bash
.venv/bin/python -c "import os,groq;from dotenv import load_dotenv;load_dotenv();print(sorted(m.id for m in groq.Groq(api_key=os.environ['GROQ_API_KEY']).models.list().data))"
```

### Turn-taking

| Variable | Default | Effect |
|---|---|---|
| `EOT_THRESHOLD` | `0.5` | Confidence needed to declare the turn over. Higher = waits longer, interrupts less. |
| `EAGER_EOT_THRESHOLD` | `0.3` | Confidence needed to *start drafting*. Lower = lower latency when the guess lands, more wasted tokens when it doesn't. |
| `EOT_TIMEOUT_MS` | `4000` | Silence that force-ends a turn at low confidence. |

The `0.5 / 0.3` defaults are measured, not guessed — see `docs/LATENCY.md`.
They are ~235 ms faster than the vendor defaults with zero premature cutoffs
across the sweep.

### Budget guards

| Variable | Default | Effect |
|---|---|---|
| `MAX_INTERVIEW_DURATION_S` | `600` | Wall-clock ceiling. |
| `MAX_GENERATION_TOKENS` | `160` | Caps one spoken response. |
| `MAX_RESPONSE_CHARS` | `400` | Caps TTS characters — a cost lever *and* a quality lever. |
| `TRANSCRIPT_WINDOW` | `12` | Turns of history sent per request. |

---

## 3. Deploying it

> **Status: designed, not built.** Nothing in this repository deploys today.
> There is no Dockerfile, no CI, no infrastructure definition. What follows is
> the path that fits the architecture — treat it as a plan to execute and
> verify, not instructions known to work.

### The constraint that drives everything

One interview holds a **WebSocket open for its entire duration**, streaming
audio in both directions. `docs/COST_MODEL.md` Note 1 records a measured
consequence: the client must keep streaming silence even when nobody is
talking, or Deepgram Flux never fires an end-of-turn.

So the server is **stateful and long-lived**, which rules out platforms built
around short request/response cycles. Serverless functions with execution caps
are the wrong shape — a ten-minute connection is the normal case here, not an
edge case.

What fits: a persistent container on Fly.io, Render, Railway, or plain ECS.
Scale on **concurrent connections**, not requests per second.

Two things that are easy to get wrong:

- **Region matters.** Response latency is already ~2 s end to end. Where the
  container runs is a latency decision, not a billing one.
- **HTTPS is mandatory.** Browsers only grant microphone access on a secure
  origin. `localhost` is exempt; your deployed domain is not.

### A starting Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY prototype/ ./prototype/
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "server:app", \
     "--app-dir", "prototype", "--host", "0.0.0.0", "--port", "8000"]
```

Note it copies `prototype/` only — `.env` must never be baked into the image.
Supply keys as platform secrets at runtime.

### Checklist before a public URL exists

- [ ] Keys injected as platform secrets, not build args or image layers
- [ ] HTTPS terminated in front of the app
- [ ] `/health` wired as the readiness probe
- [ ] Idle-connection timeout above `MAX_INTERVIEW_DURATION_S`
- [ ] WebSocket timeouts on any proxy raised past the interview length
- [ ] **Per-user metering and a hard spend cap**

The last item is not optional. Every open connection spends real money on
Deepgram for as long as it stays open, and nothing in the current code stops one
user from opening many. `docs/COST_MODEL.md` explains why `UsageRecord` and the
entitlement abstraction exist from day one rather than being retrofitted.

### What is genuinely not done

- No authentication of any kind
- No persistence — transcripts live in memory and die with the process
- No post-interview report generation (still routed to Opus in ADR-004, still
  unvalidated and still not free)
- No rate limiting or abuse protection
- No horizontal scaling story — sessions are in-process, so a second instance
  shares nothing

---

## 4. Where to read next

| File | What it covers |
|---|---|
| `docs/ARCHITECTURE.md` | System design and the three timing paths |
| `docs/DECISIONS.md` | ADRs, including the rejected options |
| `docs/LATENCY.md` | Measured numbers, and the negative result on tuning |
| `docs/COST_MODEL.md` | Per-interview cost and the free-tier operating point |
| `docs/SECURITY.md` | Threat model, prompt injection, privacy |
| `docs/TODO.md` | Prioritised remaining work |

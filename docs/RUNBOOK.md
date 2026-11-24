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
The Deepgram key stops being required only if you move *both* audio stages to
Groq, which the recommended setup below deliberately does not do.

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
{"ok":true,
 "providers":{"stt":"deepgram","tts":"deepgram","llm":"groq"},
 "keys":{"deepgram_api_key":true,"groq_api_key":true},
 "models":{"llm":"openai/gpt-oss-120b","stt":"flux-general-en","tts":"aura-2-thalia-en"},
 "free_tier":false,"speculative":true}
```

`keys` lists only the credentials your chosen providers actually need, so its
contents change with `STT_PROVIDER` / `TTS_PROVIDER` / `LLM_PROVIDER`. If any
value is `false`, that key is missing from `.env` — or `.env` was not picked up
at all, which you can check by confirming you are running from a directory where
`python-dotenv` can find it.

`speculative` reports whether speculative generation is active. It is `true`
only with `STT_PROVIDER=deepgram`, because it needs Flux's `EagerEndOfTurn`
(ADR-009). `free_tier` is `true` when all three stages are on Groq.

### Run the tests

```bash
.venv/bin/python -m pytest
```

96 tests, ~17 seconds, **no network and no API keys needed**. The vendor
providers are swapped for scripted doubles, so turn-taking is tested
deterministically. The transport suite is parametrised over five provider
combinations — including the mixed ones — with every provider class patched, so
no test ever reaches a live API.

---

## 2. Configuration

Every tunable lives in `prototype/config.py`, read from `.env`. No model ID or
vendor string appears anywhere else in the codebase.

### Credentials and routing

| Variable | Default | Notes |
|---|---|---|
| `DEEPGRAM_API_KEY` | — | Required unless *both* `STT_PROVIDER` and `TTS_PROVIDER` are `groq`. |
| `GROQ_API_KEY` | — | Required when any stage is `groq`. One key covers STT, TTS and LLM. |
| `ANTHROPIC_API_KEY` | — | Required only when `LLM_PROVIDER=anthropic`. |
| `LLM_PROVIDER` | `groq` | `groq` or `anthropic`. |
| `STT_PROVIDER` | `deepgram` | `deepgram` (Flux) or `groq` (Whisper + local VAD). See below. |
| `TTS_PROVIDER` | `deepgram` | `deepgram` (Aura-2) or `groq` (Orpheus — rejected, ADR-009). |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Also `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`. |
| `STT_MODEL` | `flux-general-en` | Deepgram Flux. Used when `STT_PROVIDER=deepgram`. |
| `TTS_MODEL` | `aura-2-thalia-en` | Deepgram Aura-2. Used when `TTS_PROVIDER=deepgram`. |
| `GROQ_STT_MODEL` | `whisper-large-v3` | Used when `STT_PROVIDER=groq`. Also `whisper-large-v3-turbo`. |
| `GROQ_TTS_MODEL` | `canopylabs/orpheus-v1-english` | Used when `TTS_PROVIDER=groq`. |
| `GROQ_TTS_VOICE` | `autumn` | `autumn`/`diana`/`hannah` (F), `austin`/`daniel`/`troy` (M). |

Each stage switches independently, and none of it needs a code change.

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

These three are read **only** when `STT_PROVIDER=deepgram`.

### Recommended setup: free speech-to-text

    STT_PROVIDER=groq
    TTS_PROVIDER=deepgram

This is the recommended configuration (ADR-009), though not the shipped default.
It moves speech-to-text onto Groq's free tier and keeps Deepgram for the voice,
taking **52% off the Deepgram bill** — $0.375 → $0.180 per 30-minute interview —
which stretches the $200 trial credit from ~530 interviews to ~1,100.

Measured trade-offs, all of them in `docs/LATENCY.md`:

| | Effect |
|---|---|
| End-of-turn, answers under ~8 s | **faster** than Flux (1157 ms vs 1295 ms) |
| End-of-turn, answers over ~8 s | slower (1603 ms at a 15.8 s answer) |
| Technical-term accuracy | **better** — WER 0.438 → 0.125 via Whisper's `prompt` |
| Speculative generation | **lost** — a VAD cannot produce `EagerEndOfTurn` |
| Net response latency | ~130 ms worse short, ~580 ms worse long |

**One caveat worth taking seriously.** Every one of those numbers came from clean
synthetic speech. That is the easiest possible input for a voice-activity
detector, and `webrtcvad` is weakest exactly where it is unrepresentative —
background noise and far-field microphones. Expect worse in a real room, treat
`VAD_AGGRESSIVENESS` and `VAD_END_SILENCE_MS` as the first things to tune, and
note that the headphones advice above matters more here than on the Deepgram
path.

`TTS_PROVIDER=groq` selects Orpheus, which is **rejected** and kept only so that
a future revisit is a config change rather than a rewrite: it is terms-gated on
the account this was built against, and ~10 req/min and ~100 req/day works out to
roughly one 30-minute interview per day. Do not switch it without reading
ADR-009.

### Turn-taking, local VAD (`STT_PROVIDER=groq` only)

| Variable | Default | Effect |
|---|---|---|
| `VAD_END_SILENCE_MS` | `700` | Silence that ends a turn. This *is* the end-of-turn latency budget — unlike Flux's confidence threshold there is nothing clever to do, so the number is the lag. Below ~500 ms an ordinary mid-sentence pause starts cutting the candidate off. |
| `VAD_START_MS` | `100` | Speech needed to open a turn. Guards against clicks and coughs. |
| `VAD_PREROLL_MS` | `300` | Audio kept from *before* the trigger, so Whisper hears the first consonant of the first word. |
| `VAD_AGGRESSIVENESS` | `2` | `webrtcvad` 0-3; higher filters more non-speech. 3 clips quiet sentence openings. |
| `STT_INTERIM_INTERVAL_S` | `4.0` | How often to transcribe an increment for the live caption. Each one is a request against a 20 RPM ceiling shared with the end-of-turn transcriptions that actually matter. `0` disables captions, which takes throughput from ~7 to ~50 interviews/day. |
| `STT_REQUESTS_PER_MINUTE` | `20` | Groq's published per-model ceiling. |
| `STT_RESERVE_REQUESTS` | `6` | Held back from captions so an end-of-turn request always gets through. |

Throughput on this path is bounded by Groq's requests-per-day rather than by
money — see `docs/COST_MODEL.md`.

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

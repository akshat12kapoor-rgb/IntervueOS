import React from "react";
import { C } from "../theme";
import { Appear, Card, Code, Kicker, MONO, Note, Scene, Title } from "../components";

export const Config: React.FC = () => (
  <Scene>
    <Kicker color={C.amber}>07 — software configuration</Kicker>
    <Title size={66}>Every tunable in one frozen dataclass</Title>
    <Appear at={0.7}>
      <div style={{ fontSize: 28, color: C.dim, marginTop: 16, marginBottom: 28, maxWidth: 1500 }}>
        No model ID or vendor string appears anywhere else in the codebase. Repricing or
        re-routing is a config change, not a code change.
      </div>
    </Appear>

    <div style={{ display: "flex", gap: 24 }}>
      <Appear at={1.4} style={{ flex: 1 }}>
        <Code size={21} highlight={[3, 4, 5]}>{`# .env

DEEPGRAM_API_KEY=...     # STT and TTS, one key
GROQ_API_KEY=...         # the interviewer
LLM_PROVIDER=groq        # groq | anthropic
STT_PROVIDER=deepgram    # deepgram | groq
TTS_PROVIDER=deepgram    # deepgram | groq
LLM_MODEL=openai/gpt-oss-120b
STT_MODEL=flux-general-en
TTS_MODEL=aura-2-thalia-en`}</Code>
      </Appear>
      <Appear at={2.2} style={{ flex: 1 }}>
        <Code size={21}>{`# turn taking
EOT_THRESHOLD=0.5         # confirm turn over
EAGER_EOT_THRESHOLD=0.3   # start drafting
EOT_TIMEOUT_MS=4000       # force-end silence

# budget guards
MAX_INTERVIEW_DURATION_S=600
MAX_GENERATION_TOKENS=160
MAX_RESPONSE_CHARS=400
TRANSCRIPT_WINDOW=12`}</Code>
      </Appear>
    </div>

    <Appear at={3.4}>
      <Card accent={C.amber} style={{ marginTop: 26 }}>
        <div style={{ fontSize: 28, lineHeight: 1.55 }}>
          <span style={{ fontFamily: MONO, color: C.amber }}>MAX_RESPONSE_CHARS</span> is a cost
          lever and a quality lever at once — TTS bills per character, and short interviewer turns
          are what a real interview sounds like anyway.
        </div>
      </Card>
    </Appear>
    <Note at={4.8}>
      LLM_PROVIDER=anthropic switches the whole interviewer back with no code change.
    </Note>
  </Scene>
);

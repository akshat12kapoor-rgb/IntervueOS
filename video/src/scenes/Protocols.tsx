import React from "react";
import { C } from "../theme";
import { Appear, Card, Code, Kicker, MONO, Note, Scene, Title } from "../components";

export const Protocols: React.FC = () => (
  <Scene>
    <Kicker color={C.violet}>05 — why any vendor can be swapped</Kicker>
    <Title size={66}>The orchestrator imports no vendor code</Title>

    <div style={{ display: "flex", gap: 26, marginTop: 34 }}>
      <Appear at={1.0} style={{ flex: 1.15 }}>
        <Code size={23}>{`# prototype/providers/base.py

class LlmProvider(Protocol):
    async def generate(
        self,
        transcript: Sequence[tuple[str, str]],
        instruction: str,
    ) -> AsyncIterator[str]:
        ...`}</Code>
      </Appear>
      <Appear at={1.9} style={{ flex: 1 }}>
        <Card accent={C.violet} style={{ height: "100%" }}>
          <div style={{ fontSize: 27, color: C.dim, lineHeight: 1.55 }}>
            One method. Stream the interviewer's next spoken turn, and be cancellable —
            barge-in kills it mid-sentence.
            <div style={{ marginTop: 18 }}>
              <span style={{ fontFamily: MONO, color: C.text }}>session.py</span> depends only on
              these Protocols. It has never imported a vendor.
            </div>
          </div>
        </Card>
      </Appear>
    </div>

    <Appear at={3.0}>
      <Card accent={C.green} style={{ marginTop: 26 }}>
        <div style={{ fontSize: 29, lineHeight: 1.55 }}>
          That is why swapping Claude for Groq was{" "}
          <span style={{ color: C.green }}>one new file and three lines</span> — and why the whole
          turn-taking suite runs in ~12 seconds against scripted doubles, with no network and no
          API keys.
        </div>
      </Card>
    </Appear>

    <Appear at={4.2} style={{ marginTop: 22, display: "flex", gap: 18 }}>
      {["SttProvider", "TtsProvider", "LlmProvider"].map((p) => (
        <div
          key={p}
          style={{
            flex: 1,
            fontFamily: MONO,
            fontSize: 24,
            color: C.text,
            background: C.panelAlt,
            border: `1px solid ${C.stroke}`,
            borderRadius: 10,
            padding: "16px 22px",
            textAlign: "center",
          }}
        >
          {p}
        </div>
      ))}
    </Appear>
    <Note at={5.4}>prototype/server.py is the only module that names a vendor — and it only constructs them.</Note>
  </Scene>
);

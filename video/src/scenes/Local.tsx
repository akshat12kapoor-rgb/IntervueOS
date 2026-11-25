import React from "react";
import { C } from "../theme";
import { Appear, Card, Code, Kicker, MONO, Note, Scene, Title } from "../components";

export const Local: React.FC = () => (
  <Scene>
    <Kicker color={C.blue}>08 — running it yourself</Kicker>
    <Title>From clone to live interview</Title>

    <Appear at={0.8} style={{ marginTop: 18 }}>
      <Code size={21} highlight={[8]}>{`git clone https://github.com/akshat12kapoor-rgb/IntervueOS
cd IntervueOS

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env        # then paste your two keys

cd prototype && ../.venv/bin/python -m uvicorn server:app --port 8000`}</Code>
    </Appear>

    <div style={{ display: "flex", gap: 22, marginTop: 22 }}>
      <Appear at={2.4} style={{ flex: 1 }}>
        <Card accent={C.green}>
          <div style={{ fontSize: 25, fontWeight: 600, marginBottom: 10 }}>Two keys, both free to start</div>
          <div style={{ fontSize: 23, color: C.dim, lineHeight: 1.5 }}>
            <span style={{ fontFamily: MONO, color: C.green }}>console.groq.com/keys</span> — free tier, no card.
            <br />
            <span style={{ fontFamily: MONO, color: C.green }}>console.deepgram.com</span> — $200 trial credit.
          </div>
        </Card>
      </Appear>
      <Appear at={3.0} style={{ flex: 1 }}>
        <Card accent={C.blue}>
          <div style={{ fontSize: 25, fontWeight: 600, marginBottom: 10 }}>Check it came up</div>
          <div style={{ fontFamily: MONO, fontSize: 21, color: C.dim, lineHeight: 1.5 }}>
            GET /health
            <br />
            → {`{"ok":true,"providers":{...},`}
            <br />
            &nbsp;&nbsp;&nbsp;{`"keys":{"groq_api_key":true, ...}}`}
          </div>
        </Card>
      </Appear>
      <Appear at={3.6} style={{ flex: 1 }}>
        <Card accent={C.red}>
          <div style={{ fontSize: 25, fontWeight: 600, marginBottom: 10 }}>Wear headphones</div>
          <div style={{ fontSize: 23, color: C.dim, lineHeight: 1.5 }}>
            Without them your speakers feed the interviewer's own voice back into the mic, and
            barge-in fires constantly.
          </div>
        </Card>
      </Appear>
    </div>

    <Appear at={4.6}>
      <div style={{ fontSize: 28, color: C.text, marginTop: 24, lineHeight: 1.45 }}>
        Then open <span style={{ fontFamily: MONO, color: C.blue }}>http://127.0.0.1:8000</span>,
        paste a job description and your resume, and press Start.
      </div>
    </Appear>
    <Note at={5.6}>
      Python 3.12+, and Node is not required. Tests:{" "}
      <span style={{ fontFamily: MONO }}>.venv/bin/python -m pytest</span> — 114 of them, ~17 s,
      no network and no API keys.
    </Note>
  </Scene>
);

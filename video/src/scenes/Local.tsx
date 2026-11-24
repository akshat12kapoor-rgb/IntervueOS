import React from "react";
import { C } from "../theme";
import { Appear, Card, Code, Kicker, MONO, Note, Scene, Title } from "../components";

export const Local: React.FC = () => (
  <Scene>
    <Kicker color={C.blue}>08 — running it yourself</Kicker>
    <Title>From clone to live interview</Title>

    <Appear at={0.8} style={{ marginTop: 26 }}>
      <Code size={22} highlight={[8]}>{`git clone https://github.com/akshat12kapoor-rgb/IntervueOS
cd IntervueOS

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env        # then paste your two keys

cd prototype && ../.venv/bin/python -m uvicorn server:app --port 8000`}</Code>
    </Appear>

    <div style={{ display: "flex", gap: 22, marginTop: 28 }}>
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
      <div style={{ fontSize: 29, color: C.text, marginTop: 30, lineHeight: 1.5 }}>
        Then open <span style={{ fontFamily: MONO, color: C.blue }}>http://127.0.0.1:8000</span>,
        paste a job description and your resume, and press Start. Tests:{" "}
        <span style={{ fontFamily: MONO }}>.venv/bin/python -m pytest</span> — 33 of them, ~12 s,
        no network needed.
      </div>
    </Appear>
    <Note at={6}>Python 3.12+. Node is not required to run the prototype.</Note>
  </Scene>
);

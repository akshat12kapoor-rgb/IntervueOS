import React from "react";
import { C } from "../theme";
import { Appear, Card, Code, Kicker, MONO, Note, Pill, Scene, Title } from "../components";

export const Deploy: React.FC = () => (
  <Scene>
    <Kicker color={C.red}>09 — deployment</Kicker>
    <Title size={66}>A stateful socket, not a serverless function</Title>

    <Appear at={0.7}>
      <Card accent={C.amber} style={{ marginTop: 22 }}>
        <div style={{ fontSize: 27, lineHeight: 1.5 }}>
          <span style={{ color: C.amber, fontWeight: 600 }}>Not yet built.</span> Nothing in the
          repository deploys today — this is the designed path, not a tested one.
        </div>
      </Card>
    </Appear>

    <Appear at={1.8}>
      <div style={{ fontSize: 28, color: C.dim, marginTop: 26, marginBottom: 22, maxWidth: 1620, lineHeight: 1.5 }}>
        One interview holds a WebSocket open for its entire duration, streaming audio both ways.
        That rules out platforms built around short request/response.
      </div>
    </Appear>

    <div style={{ display: "flex", gap: 20, marginBottom: 26 }}>
      <Appear at={2.4} style={{ flex: 1 }}>
        <Card accent={C.red} style={{ height: 210 }}>
          <Pill color={C.red}>wrong shape</Pill>
          <div style={{ fontSize: 24, color: C.dim, marginTop: 16, lineHeight: 1.5 }}>
            Serverless functions with execution caps. A 10-minute connection is the normal case
            here, not an edge case.
          </div>
        </Card>
      </Appear>
      <Appear at={2.9} style={{ flex: 1 }}>
        <Card accent={C.green} style={{ height: 210 }}>
          <Pill color={C.green}>right shape</Pill>
          <div style={{ fontSize: 24, color: C.dim, marginTop: 16, lineHeight: 1.5 }}>
            A persistent container — Fly.io, Render, Railway, or plain ECS. Scale on concurrent
            connections, not requests per second.
          </div>
        </Card>
      </Appear>
      <Appear at={3.4} style={{ flex: 1 }}>
        <Card accent={C.blue} style={{ height: 210 }}>
          <Pill color={C.blue}>place it near people</Pill>
          <div style={{ fontSize: 24, color: C.dim, marginTop: 16, lineHeight: 1.5 }}>
            Round trips are already ~2 s. Region choice is a latency decision, not a billing one.
          </div>
        </Card>
      </Appear>
    </div>

    <div style={{ display: "flex", gap: 24 }}>
      <Appear at={4.2} style={{ flex: 1.1 }}>
        <Code size={20}>{`FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY prototype/ ./prototype/
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "server:app", \\
     "--app-dir", "prototype", \\
     "--host", "0.0.0.0", "--port", "8000"]`}</Code>
      </Appear>
      <Appear at={4.9} style={{ flex: 1 }}>
        <Card accent={C.violet} style={{ height: "100%" }}>
          <div style={{ fontSize: 25, fontWeight: 600, marginBottom: 14 }}>Before it is real</div>
          <div style={{ fontSize: 23, color: C.dim, lineHeight: 1.65 }}>
            · Keys as platform secrets — never baked into the image
            <br />· HTTPS, so the browser will grant the microphone
            <br />· <span style={{ fontFamily: MONO }}>/health</span> as the readiness probe
            <br />· Per-user metering before a public URL exists
          </div>
        </Card>
      </Appear>
    </div>
    <Note at={6.4}>
      The last one is not optional: every connection spends real money on Deepgram for as long as
      it stays open.
    </Note>
  </Scene>
);

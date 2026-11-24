import React from "react";
import { C } from "../theme";
import { Appear, Body, Card, Kicker, MONO, Note, Scene, Title } from "../components";

const Box: React.FC<{ t: string; s: string; at: number; accent: string; w?: number }> = ({
  t, s, at, accent, w,
}) => (
  <Appear at={at} style={{ flex: w ? undefined : 1, width: w }}>
    <Card accent={accent} style={{ height: 160 }}>
      <div style={{ fontSize: 28, fontWeight: 600, marginBottom: 10 }}>{t}</div>
      <div style={{ fontSize: 22, color: C.dim, lineHeight: 1.45 }}>{s}</div>
    </Card>
  </Appear>
);

export const Target: React.FC = () => (
  <Scene>
    <Kicker>02 — system design</Kicker>
    <Title>One deployable unit, three engines</Title>
    <Body size={28}>
      <div style={{ marginTop: 18, marginBottom: 34 }}>
        A modular monolith. Services get extracted only when a measurement says so.
      </div>
    </Body>

    <Appear at={1.2}>
      <Card accent={C.blue} style={{ marginBottom: 20 }}>
        <div style={{ fontFamily: MONO, fontSize: 25, color: C.text }}>
          Next.js frontend &nbsp;──HTTPS──▶&nbsp; FastAPI &nbsp;──▶&nbsp; Postgres · object storage
        </div>
        <div style={{ fontFamily: MONO, fontSize: 23, color: C.blue, marginTop: 12 }}>
          └── WebSocket (audio) ──────────────┘
        </div>
      </Card>
    </Appear>

    <div style={{ display: "flex", gap: 20, marginBottom: 20 }}>
      <Box at={2.1} accent={C.green} t="Interview Engine" s="State machine, objective selection, scoring aggregation." />
      <Box at={2.5} accent={C.amber} t="Document Engine" s="Parse and structure the job description and resume." />
      <Box at={2.9} accent={C.violet} t="User Engine" s="Auth, plans, entitlements, usage metering." />
    </div>

    <Appear at={3.6}>
      <Card accent={C.red}>
        <div style={{ fontSize: 26, fontWeight: 600, marginBottom: 8 }}>Provider Layer</div>
        <div style={{ fontFamily: MONO, fontSize: 24, color: C.dim }}>
          SttProvider · TtsProvider · LlmProvider · StorageProvider
        </div>
      </Card>
    </Appear>
    <Note at={4.8}>
      The first service to be extracted will be the voice loop — long-lived connections scale
      differently from short requests.
    </Note>
  </Scene>
);

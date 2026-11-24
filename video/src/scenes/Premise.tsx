import React from "react";
import { C } from "../theme";
import { Appear, Body, Card, Kicker, Note, Scene, Title, MONO } from "../components";

const Row: React.FC<{ a: string; b: string; good?: boolean; at: number }> = ({ a, b, good, at }) => (
  <Appear at={at}>
    <Card accent={good ? C.green : C.faint} style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 22 }}>
        <div style={{ fontFamily: MONO, fontSize: 25, color: good ? C.green : C.text, width: 400 }}>
          {a}
        </div>
        <div style={{ fontSize: 26, color: C.dim }}>{b}</div>
      </div>
    </Card>
  </Appear>
);

export const Premise: React.FC = () => (
  <Scene>
    <Kicker>01 — the shape of the problem</Kicker>
    <Title>Two ways to build a voice agent</Title>
    <Body size={29} color={C.dim}>
      <div style={{ marginTop: 22, marginBottom: 40 }}>
        A speech-to-speech model is one API call. A cascaded pipeline is three.
        IntervueOS takes the harder road deliberately.
      </div>
    </Body>
    <Row at={1.6} a="speech-to-speech" b="One vendor owns the whole loop. Fast to build, opaque to inspect, and you still need a separate transcription pass to produce a report." />
    <Row at={2.5} good a="cascaded  STT → LLM → TTS" b="Three swappable providers. You see every transcript, control every turn, and can replace any stage without touching the others." />
    <Appear at={3.6} style={{ marginTop: 36 }}>
      <div style={{ fontSize: 30, color: C.text, lineHeight: 1.5, maxWidth: 1480 }}>
        The product is not the conversation — it is the{" "}
        <span style={{ color: C.blue }}>evidence-based report afterwards</span>. That
        requires structured access to every turn, which the cascade gives for free.
      </div>
    </Appear>
    <Note at={5}>docs/DECISIONS.md — ADR-001</Note>
  </Scene>
);

import React from "react";
import { C } from "../theme";
import { Appear, Card, Kicker, Note, Scene, Title } from "../components";

const rows: [string, string][] = [
  ["How much time is left", "How to phrase a question"],
  ["Which topic is current", "Which claim in an answer to pull on"],
  ["Whether the thread is exhausted", "What follow-up actually probes it"],
  ["Whether an answer was vague or thin", "Whether an answer was correct"],
  ["When to wrap up", "What the wrap-up sounds like"],
];

export const Division: React.FC = () => (
  <Scene>
    <Kicker color={C.green}>06 — the design decision that matters most</Kicker>
    <Title>The model never chooses the objective</Title>

    <div style={{ display: "flex", gap: 24, marginTop: 36 }}>
      <Appear at={0.9} style={{ flex: 1 }}>
        <Card accent={C.green}>
          <div style={{ fontSize: 26, fontWeight: 600, color: C.green, marginBottom: 18 }}>
            Decided by code — interview.py
          </div>
          {rows.map(([a], i) => (
            <Appear key={i} at={1.4 + i * 0.28}>
              <div style={{ fontSize: 25, color: C.text, padding: "11px 0", borderBottom: `1px solid ${C.stroke}` }}>
                {a}
              </div>
            </Appear>
          ))}
        </Card>
      </Appear>
      <Appear at={1.1} style={{ flex: 1 }}>
        <Card accent={C.amber}>
          <div style={{ fontSize: 26, fontWeight: 600, color: C.amber, marginBottom: 18 }}>
            Decided by the model
          </div>
          {rows.map(([, b], i) => (
            <Appear key={i} at={1.6 + i * 0.28}>
              <div style={{ fontSize: 25, color: C.dim, padding: "11px 0", borderBottom: `1px solid ${C.stroke}` }}>
                {b}
              </div>
            </Appear>
          ))}
        </Card>
      </Appear>
    </div>

    <Appear at={3.6}>
      <div style={{ fontSize: 30, color: C.text, marginTop: 30, lineHeight: 1.5, maxWidth: 1620 }}>
        The engine hands the model an objective — <span style={{ color: C.blue }}>probe</span>,{" "}
        <span style={{ color: C.blue }}>challenge</span>,{" "}
        <span style={{ color: C.blue }}>specificity</span> — and the model only phrases it. That is
        what makes an interview reproducible, time-bounded, and analysable afterwards.
      </div>
    </Appear>
    <Note at={5}>It is also why the report can say what the interviewer was testing on every question.</Note>
  </Scene>
);

import React from "react";
import { C } from "../theme";
import { Appear, Card, Kicker, MONO, Note, Scene, Title } from "../components";

const Score: React.FC<{ n: number | null }> = ({ n }) => {
  const color = n === null ? C.faint : n >= 4 ? C.green : n <= 2 ? C.red : C.amber;
  return (
    <span
      style={{
        fontFamily: MONO, fontSize: 22, fontWeight: 700, color,
        background: `${color}1f`, borderRadius: 6, padding: "3px 11px",
        minWidth: 62, textAlign: "center", flex: "none",
      }}
    >
      {n === null ? "—" : `${n}/5`}
    </span>
  );
};

const Row: React.FC<{
  at: number; score: number | null; q: string; testing: string; note: string;
}> = ({ at, score, q, testing, note }) => (
  <Appear at={at}>
    <Card style={{ marginBottom: 12, padding: "16px 20px" }}>
      <div style={{ display: "flex", gap: 16, alignItems: "baseline" }}>
        <Score n={score} />
        <div style={{ fontSize: 24, fontWeight: 600 }}>{q}</div>
      </div>
      <div style={{ fontFamily: MONO, fontSize: 17, color: C.faint, margin: "8px 0 0 78px",
                    textTransform: "uppercase", letterSpacing: 1.2 }}>
        Testing: {testing}
      </div>
      <div style={{ fontSize: 21, color: C.dim, margin: "6px 0 0 78px" }}>{note}</div>
    </Card>
  </Appear>
);

export const Report: React.FC = () => (
  <Scene>
    <Kicker color={C.green}>10 — the post-interview report</Kicker>
    <Title size={62}>The conversation is not the product</Title>
    <Appear at={0.7}>
      <div style={{ fontSize: 27, color: C.dim, marginTop: 14, marginBottom: 24, maxWidth: 1600 }}>
        The report is. Each question is paired with the answer it drew and the objective the
        engine chose — so it states what was being tested instead of guessing.
      </div>
    </Appear>

    <Row at={1.5} score={4} q="What was the latency before and after?"
         testing="go one level deeper on what you had just said"
         note="You supplied concrete numbers before and after the change." />
    <Row at={2.2} score={2} q="What did you specifically do, as opposed to the team?"
         testing="pin down what you specifically did, concretely"
         note="You answered with a vague team-wide statement and did not isolate your own actions." />
    <Row at={2.9} score={null} q="Let's talk about how it failed."
         testing="move to a new topic"
         note="A topic change, not a question under examination — not scored." />

    <Appear at={3.9}>
      <Card accent={C.green} style={{ marginTop: 18 }}>
        <div style={{ fontSize: 26, lineHeight: 1.5 }}>
          Pairing, objectives and timings are computed in{" "}
          <span style={{ fontFamily: MONO, color: C.green }}>report.py</span> with no model
          involved, so that half cannot hallucinate. The LLM only judges — and every claim it
          makes must quote words the candidate actually said.
        </div>
      </Card>
    </Appear>
    <Note at={5}>
      Generated on Groq at high reasoning effort — ~6 s, and nobody is waiting. Held in memory,
      not persisted.
    </Note>
  </Scene>
);

import React from "react";
import { interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FPS } from "../theme";
import { Appear, Card, Kicker, MONO, Note, Pill, Scene, Title } from "../components";

/** A horizontal time axis with labelled stops, swept by a playhead. */
const Timeline: React.FC<{
  stops: { at: number; label: string; ms: string; color: string }[];
  span: number;
  startAt: number;
}> = ({ stops, span, startAt }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = interpolate(frame - startAt * fps, [0, 5 * fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const x0 = 140;
  const x1 = 1780;
  const head = x0 + (x1 - x0) * t;
  return (
    <div style={{ position: "relative", height: 300, marginTop: 30 }}>
      <svg style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 300 }}>
        <line x1={x0} y1={120} x2={x1} y2={120} stroke={C.stroke} strokeWidth={3} />
        <line x1={x0} y1={120} x2={head} y2={120} stroke={C.blue} strokeWidth={3} />
        {stops.map((s, i) => {
          const x = x0 + (x1 - x0) * (s.at / span);
          const lit = head >= x - 2;
          return (
            <g key={i}>
              <line x1={x} y1={104} x2={x} y2={136} stroke={lit ? s.color : C.stroke} strokeWidth={3} />
              <circle cx={x} cy={120} r={lit ? 10 : 6} fill={lit ? s.color : C.stroke} />
            </g>
          );
        })}
        <circle cx={head} cy={120} r={6} fill={C.text} />
      </svg>
      {stops.map((s, i) => {
        const x = x0 + (x1 - x0) * (s.at / span);
        const lit = head >= x - 2;
        const below = i % 2 === 1;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x - 115,
              top: below ? 150 : 8,
              width: 230,
              textAlign: "center",
              opacity: lit ? 1 : 0.28,
            }}
          >
            <div style={{ fontSize: 23, color: lit ? C.text : C.faint, lineHeight: 1.3 }}>{s.label}</div>
            <div style={{ fontFamily: MONO, fontSize: 21, color: s.color, marginTop: 5 }}>{s.ms}</div>
          </div>
        );
      })}
    </div>
  );
};

const Normal: React.FC = () => (
  <Scene>
    <Kicker>04 — timing path 1 of 3</Kicker>
    <Title>The normal turn</Title>
    <Timeline
      startAt={1}
      span={1700}
      stops={[
        { at: 0, label: "candidate stops", ms: "0 ms", color: C.faint },
        { at: 1300, label: "EndOfTurn fires", ms: "~1300 ms", color: C.amber },
        { at: 1470, label: "LLM first token", ms: "+470 ms*", color: C.violet },
        { at: 1640, label: "first TTS byte", ms: "+334 ms", color: C.green },
        { at: 1700, label: "audible word", ms: "+10 ms", color: C.blue },
      ]}
    />
    <Appear at={5.6}>
      <Card accent={C.amber} style={{ marginTop: 10 }}>
        <div style={{ fontSize: 30, lineHeight: 1.5 }}>
          Detecting that the candidate <em>stopped talking</em> costs ~1.3 s — more than
          the LLM and TTS combined. Sweeping the threshold across its whole supported
          range recovered only <span style={{ color: C.amber }}>235 ms</span>.
        </div>
      </Card>
    </Appear>
    <Note at={7.4}>
      *LLM figure measured on Groq. The rest from the live sweep in docs/LATENCY.md — synthetic
      speech, so treat them as a best case.
    </Note>
  </Scene>
);

const Speculative: React.FC = () => (
  <Scene>
    <Kicker color={C.green}>04 — timing path 2 of 3</Kicker>
    <Title>The speculative turn</Title>
    <Appear at={0.8}>
      <div style={{ fontSize: 30, color: C.dim, marginTop: 18, maxWidth: 1500, lineHeight: 1.5 }}>
        <span style={{ fontFamily: MONO, color: C.green }}>EagerEndOfTurn</span> fires a few hundred
        milliseconds before the turn is confirmed. Generation starts on a guess.
      </div>
    </Appear>
    <div style={{ display: "flex", gap: 22, marginTop: 44 }}>
      <Appear at={1.8} style={{ flex: 1 }}>
        <Card accent={C.green} style={{ height: 330 }}>
          <Pill color={C.green}>bet pays off</Pill>
          <div style={{ fontSize: 27, color: C.dim, marginTop: 20, lineHeight: 1.55 }}>
            The final transcript matches what was drafted from. The buffered fragments go
            straight to TTS — the model round trip already happened, so it costs nothing.
          </div>
        </Card>
      </Appear>
      <Appear at={2.6} style={{ flex: 1 }}>
        <Card accent={C.red} style={{ height: 330 }}>
          <Pill color={C.red}>bet loses</Pill>
          <div style={{ fontSize: 27, color: C.dim, marginTop: 20, lineHeight: 1.55 }}>
            The transcript changed, or{" "}
            <span style={{ fontFamily: MONO, color: C.red }}>TurnResumed</span> arrived because the
            candidate was only pausing. The draft is cancelled and discarded.
          </div>
        </Card>
      </Appear>
    </div>
    <Appear at={3.8}>
      <Card accent={C.blue} style={{ marginTop: 26 }}>
        <div style={{ fontSize: 29, lineHeight: 1.5 }}>
          Measured: eager fired on <span style={{ color: C.green }}>8 of 8</span> utterances and the
          transcript matched <span style={{ color: C.green }}>8 of 8</span> times. The session
          summary reports <span style={{ fontFamily: MONO }}>speculation_hit_rate</span> so the bet
          stays honest.
        </div>
      </Card>
    </Appear>
    <Note at={5.4}>Wasted tokens are the price of a wrong guess — which is why the hit rate is logged.</Note>
  </Scene>
);

const BargeIn: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const steps = [
    { t: "Cancel the generation task", s: "asyncio task cancelled mid-stream", at: 2.0, color: C.violet },
    { t: "Clear the TTS vendor buffer", s: "Deepgram keeps ~0.92 s queued without it", at: 2.8, color: C.amber },
    { t: "Flush the browser playback queue", s: 'emit {"type":"interrupt"} → worklet ring buffer', at: 3.6, color: C.blue },
  ];
  return (
    <Scene>
      <Kicker color={C.red}>04 — timing path 3 of 3</Kicker>
      <Title>Barge-in</Title>
      <Appear at={0.8}>
        <div style={{ fontSize: 30, color: C.dim, marginTop: 18, maxWidth: 1540, lineHeight: 1.5 }}>
          <span style={{ fontFamily: MONO, color: C.red }}>StartOfTurn</span> while the interviewer
          holds the floor. Three things must be cancelled, in order.
        </div>
      </Appear>
      <div style={{ marginTop: 40 }}>
        {steps.map((s, i) => (
          <Appear key={i} at={s.at}>
            <Card accent={s.color} style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
                <div style={{ fontFamily: MONO, fontSize: 34, color: s.color, width: 44 }}>{i + 1}</div>
                <div>
                  <div style={{ fontSize: 29, fontWeight: 600 }}>{s.t}</div>
                  <div style={{ fontFamily: MONO, fontSize: 21, color: C.faint, marginTop: 6 }}>{s.s}</div>
                </div>
              </div>
            </Card>
          </Appear>
        ))}
      </div>
      <Appear at={4.8}>
        <div style={{ fontSize: 30, color: C.text, marginTop: 26, lineHeight: 1.5 }}>
          Skip any one of the three and the interviewer talks over the candidate.
          Measured client-side flush: <span style={{ color: C.red, fontFamily: MONO }}>11 ms</span>.
        </div>
      </Appear>
      <Note at={6}>Use headphones — speaker bleed reads to the system as a genuine interruption.</Note>
    </Scene>
  );
};

export const Timing: React.FC = () => (
  <>
    <Sequence durationInFrames={25 * FPS} premountFor={FPS}>
      <Normal />
    </Sequence>
    <Sequence from={25 * FPS} durationInFrames={25 * FPS} premountFor={FPS}>
      <Speculative />
    </Sequence>
    <Sequence from={50 * FPS} durationInFrames={24 * FPS} premountFor={FPS}>
      <BargeIn />
    </Sequence>
  </>
);

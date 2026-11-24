import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { C } from "../theme";
import { Appear, Kicker, MONO, Note, Scene, Title } from "../components";

const Node: React.FC<{
  x: number; y: number; label: string; sub?: string; accent: string; at: number;
}> = ({ x, y, label, sub, accent, at }) => (
  <Appear at={at} style={{ position: "absolute", left: x, top: y }}>
    <div
      style={{
        background: C.panel,
        border: `1px solid ${C.stroke}`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: 11,
        padding: "16px 22px",
        minWidth: 250,
      }}
    >
      <div style={{ fontSize: 25, fontWeight: 600 }}>{label}</div>
      {sub ? (
        <div style={{ fontFamily: MONO, fontSize: 19, color: C.faint, marginTop: 6 }}>{sub}</div>
      ) : null}
    </div>
  </Appear>
);

/** A packet travelling a polyline, so the diagram reads as a flow. */
const Flow: React.FC<{ pts: [number, number][]; at: number; color: string }> = ({ pts, at, color }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = (frame - at * fps) / (1.9 * fps);
  const p = ((t % 1) + 1) % 1;
  const on = frame > at * fps;

  const segs = pts.slice(1).map((pt, i) => {
    const a = pts[i];
    return Math.hypot(pt[0] - a[0], pt[1] - a[1]);
  });
  const totalLen = segs.reduce((x, y) => x + y, 0);
  let want = p * totalLen;
  let cx = pts[0][0];
  let cy = pts[0][1];
  for (let i = 0; i < segs.length; i++) {
    if (want <= segs[i]) {
      const f = segs[i] === 0 ? 0 : want / segs[i];
      cx = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f;
      cy = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f;
      break;
    }
    want -= segs[i];
    cx = pts[i + 1][0];
    cy = pts[i + 1][1];
  }

  return (
    <svg style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, pointerEvents: "none" }}>
      <polyline
        points={pts.map((q) => q.join(",")).join(" ")}
        fill="none"
        stroke={C.stroke}
        strokeWidth={2}
      />
      {on ? <circle cx={cx} cy={cy} r={7} fill={color} /> : null}
    </svg>
  );
};

export const Loop: React.FC = () => (
  <Scene>
    <Kicker>03 — the voice loop as built</Kicker>
    <Title size={64}>Audio in, audio out, every hop streaming</Title>

    <Node at={1.0} x={110} y={300} label="Browser mic" sub="AudioWorklet · 80ms · PCM16 16kHz" accent={C.blue} />
    <Flow pts={[[420, 342], [720, 342]]} at={1.4} color={C.blue} />
    <Node at={1.6} x={720} y={300} label="Deepgram Flux" sub="STT + turn detection" accent={C.green} />

    <Flow pts={[[900, 388], [900, 468]]} at={2.0} color={C.green} />
    <Node at={2.2} x={720} y={468} label="InterviewSession" sub="session.py — the orchestrator" accent={C.violet} />

    <Flow pts={[[900, 556], [900, 636]]} at={2.6} color={C.violet} />
    <Node at={2.8} x={720} y={636} label="Groq LLM" sub="openai/gpt-oss-120b" accent={C.amber} />

    <Flow pts={[[1040, 678], [1380, 678]]} at={3.2} color={C.amber} />
    <Node at={3.4} x={1380} y={636} label="Deepgram Aura-2" sub="TTS · PCM16 24kHz" accent={C.red} />

    {/* return leg routed below everything, never across a card */}
    <Flow pts={[[1510, 724], [1510, 900], [155, 900], [155, 388]]} at={3.9} color={C.red} />

    <Appear at={4.5} style={{ position: "absolute", left: 205, top: 470, width: 470 }}>
      <div style={{ fontSize: 26, color: C.dim, lineHeight: 1.5 }}>
        The candidate hears the first words of a question while the rest is still being
        generated — the LLM streams fragments, and TTS speaks them a sentence at a time.
      </div>
    </Appear>
    <Appear at={5.2} style={{ position: "absolute", left: 300, top: 912 }}>
      <div style={{ fontFamily: MONO, fontSize: 20, color: C.faint }}>
        PCM16 24kHz back over the same WebSocket → worklet ring buffer
      </div>
    </Appear>
    <Note at={6}>prototype/session.py holds all of this. prototype/server.py only moves bytes.</Note>
  </Scene>
);

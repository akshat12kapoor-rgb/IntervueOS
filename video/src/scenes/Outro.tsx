import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { C } from "../theme";
import { Appear, MONO, SANS } from "../components";

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [300, 380], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.bg,
        fontFamily: SANS,
        color: C.text,
        justifyContent: "center",
        padding: 150,
        opacity: o,
      }}
    >
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(circle at 70% 60%, rgba(124,156,245,0.15), transparent 58%)`,
        }}
      />
      <Appear at={0.2}>
        <div style={{ fontSize: 60, fontWeight: 700, letterSpacing: -1.6, lineHeight: 1.2, maxWidth: 1400 }}>
          Swappable providers, a deterministic interview engine, and a loop you can
          measure.
        </div>
      </Appear>
      <Appear at={1.6} style={{ marginTop: 44 }}>
        <div style={{ fontFamily: MONO, fontSize: 28, color: C.blue }}>
          github.com/akshat12kapoor-rgb/IntervueOS
        </div>
      </Appear>
      <Appear at={2.4} style={{ marginTop: 18 }}>
        <div style={{ fontSize: 26, color: C.faint }}>
          docs/ARCHITECTURE.md · docs/DECISIONS.md · docs/LATENCY.md · docs/COST_MODEL.md
        </div>
      </Appear>
    </AbsoluteFill>
  );
};

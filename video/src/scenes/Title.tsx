import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { C } from "../theme";
import { Appear, MONO, SANS, Pill } from "../components";

export const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const line = interpolate(frame, [10, 50], [0, 1], {
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
      }}
    >
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(circle at 26% 40%, rgba(124,156,245,0.17), transparent 56%)`,
        }}
      />
      <Appear at={0.2}>
        <div style={{ fontSize: 112, fontWeight: 700, letterSpacing: -3 }}>IntervueOS</div>
      </Appear>
      <div
        style={{
          height: 3,
          background: C.blue,
          width: `${line * 300}px`,
          margin: "32px 0 34px",
        }}
      />
      <Appear at={1.3}>
        <div style={{ fontSize: 38, color: C.dim, maxWidth: 1250, lineHeight: 1.45 }}>
          A real-time adaptive AI interview simulator — and a walkthrough of how
          every part of it actually works.
        </div>
      </Appear>
      <Appear at={2.4} style={{ display: "flex", gap: 16, marginTop: 48 }}>
        <Pill color={C.blue}>architecture</Pill>
        <Pill color={C.green}>timing paths</Pill>
        <Pill color={C.amber}>configuration</Pill>
        <Pill color={C.violet}>running it</Pill>
        <Pill color={C.red}>deployment</Pill>
      </Appear>
      <Appear at={3.4} style={{ marginTop: 70 }}>
        <div style={{ fontFamily: MONO, fontSize: 24, color: C.faint }}>
          github.com/akshat12kapoor-rgb/IntervueOS
        </div>
      </Appear>
    </AbsoluteFill>
  );
};

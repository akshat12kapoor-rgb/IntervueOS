import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { C } from "./theme";
import { loadFont as loadSans } from "@remotion/google-fonts/Inter";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

// loadFont() blocks rendering until the font is ready; the package exports
// the loader, not a ready-made family string.
export const SANS = loadSans().fontFamily;
export const MONO = loadMono().fontFamily;

/** Fade + lift, driven by frame. No CSS transitions anywhere. */
export const Appear: React.FC<{
  at?: number;
  children: React.ReactNode;
  lift?: number;
  style?: React.CSSProperties;
}> = ({ at = 0, children, lift = 18, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - at * fps;
  const o = interpolate(t, [0, 0.45 * fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = interpolate(t, [0, 0.55 * fps], [lift, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <div style={{ opacity: o, transform: `translateY(${y}px)`, ...style }}>{children}</div>;
};

export const Pop: React.FC<{ at?: number; children: React.ReactNode; style?: React.CSSProperties }> = ({
  at = 0,
  children,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - at * fps, fps, config: { damping: 14, stiffness: 120 } });
  return <div style={{ transform: `scale(${s})`, opacity: s, ...style }}>{children}</div>;
};

export const Scene: React.FC<{ children: React.ReactNode; pad?: number }> = ({ children, pad = 110 }) => (
  <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily: SANS, color: C.text, padding: pad }}>
    <Grid />
    {children}
  </AbsoluteFill>
);

/** Faint dot grid so flat backgrounds don't read as dead space. */
const Grid: React.FC = () => (
  <AbsoluteFill
    style={{
      backgroundImage: `radial-gradient(${C.stroke} 1px, transparent 1px)`,
      backgroundSize: "46px 46px",
      opacity: 0.4,
    }}
  />
);

export const Kicker: React.FC<{ children: React.ReactNode; color?: string }> = ({
  children,
  color = C.blue,
}) => (
  <div
    style={{
      fontFamily: MONO,
      fontSize: 23,
      letterSpacing: 3.4,
      textTransform: "uppercase",
      color,
      marginBottom: 20,
    }}
  >
    {children}
  </div>
);

export const Title: React.FC<{ children: React.ReactNode; size?: number }> = ({
  children,
  size = 74,
}) => (
  <div style={{ fontSize: size, fontWeight: 700, letterSpacing: -1.6, lineHeight: 1.08 }}>
    {children}
  </div>
);

export const Body: React.FC<{ children: React.ReactNode; size?: number; color?: string }> = ({
  children,
  size = 31,
  color = C.dim,
}) => (
  <div style={{ fontSize: size, lineHeight: 1.55, color, maxWidth: 1400 }}>{children}</div>
);

export const Card: React.FC<{
  children: React.ReactNode;
  accent?: string;
  style?: React.CSSProperties;
}> = ({ children, accent = C.stroke, style }) => (
  <div
    style={{
      background: C.panel,
      border: `1px solid ${C.stroke}`,
      borderTop: `3px solid ${accent}`,
      borderRadius: 14,
      padding: "26px 30px",
      ...style,
    }}
  >
    {children}
  </div>
);

export const Code: React.FC<{ children: string; size?: number; highlight?: number[] }> = ({
  children,
  size = 25,
  highlight = [],
}) => {
  const lines = children.replace(/\n$/, "").split("\n");
  return (
    <div
      style={{
        background: "#0E1016",
        border: `1px solid ${C.stroke}`,
        borderRadius: 12,
        padding: "24px 28px",
        fontFamily: MONO,
        fontSize: size,
        lineHeight: 1.72,
      }}
    >
      {lines.map((l, i) => (
        <div
          key={i}
          style={{
            color: highlight.includes(i) ? C.text : l.trimStart().startsWith("#") ? C.faint : C.dim,
            background: highlight.includes(i) ? "rgba(124,156,245,0.12)" : undefined,
            borderLeft: highlight.includes(i) ? `3px solid ${C.blue}` : "3px solid transparent",
            paddingLeft: 14,
            whiteSpace: "pre",
          }}
        >
          {l === "" ? " " : l}
        </div>
      ))}
    </div>
  );
};

/** Caption bar pinned bottom-left; the spoken-word layer of the video. */
export const Note: React.FC<{ children: React.ReactNode; at?: number }> = ({ children, at = 0 }) => (
  <Appear at={at} style={{ position: "absolute", left: 110, right: 110, bottom: 74 }}>
    <div
      style={{
        fontSize: 27,
        color: C.faint,
        borderLeft: `3px solid ${C.stroke}`,
        paddingLeft: 20,
        lineHeight: 1.5,
      }}
    >
      {children}
    </div>
  </Appear>
);

export const Pill: React.FC<{ children: React.ReactNode; color: string }> = ({ children, color }) => (
  <span
    style={{
      fontFamily: MONO,
      fontSize: 20,
      color,
      border: `1px solid ${color}55`,
      background: `${color}14`,
      borderRadius: 999,
      padding: "6px 16px",
      whiteSpace: "nowrap",
    }}
  >
    {children}
  </span>
);

import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { C, FPS, SCENES } from "./theme";
import { MONO } from "./components";
import { Title } from "./scenes/Title";
import { Premise } from "./scenes/Premise";
import { Target } from "./scenes/Target";
import { Loop } from "./scenes/Loop";
import { Timing } from "./scenes/Timing";
import { Protocols } from "./scenes/Protocols";
import { Division } from "./scenes/Division";
import { Config } from "./scenes/Config";
import { Local } from "./scenes/Local";
import { Report } from "./scenes/Report";
import { Deploy } from "./scenes/Deploy";
import { Outro } from "./scenes/Outro";

const ORDER = [
  ["title", Title],
  ["premise", Premise],
  ["target", Target],
  ["loop", Loop],
  ["timing", Timing],
  ["protocols", Protocols],
  ["division", Division],
  ["config", Config],
  ["local", Local],
  ["report", Report],
  ["deploy", Deploy],
  ["outro", Outro],
] as const;

/** Thin progress rule along the bottom so length is legible at a glance. */
const Progress: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / durationInFrames;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{ position: "absolute", bottom: 0, left: 0, height: 4, width: "100%", background: C.stroke }} />
      <div style={{ position: "absolute", bottom: 0, left: 0, height: 4, width: `${p * 100}%`, background: C.blue }} />
    </AbsoluteFill>
  );
};

/** Short cross-fade so cuts don't jar. */
const Fade: React.FC<{ children: React.ReactNode; dur: number }> = ({ children, dur }) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [0, 10, dur - 10, dur], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <AbsoluteFill style={{ opacity: o }}>{children}</AbsoluteFill>;
};

export const Walkthrough: React.FC = () => {
  let at = 0;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      {ORDER.map(([key, Comp]) => {
        const dur = SCENES[key as keyof typeof SCENES] * FPS;
        const from = at;
        at += dur;
        return (
          <Sequence key={key} from={from} durationInFrames={dur} premountFor={FPS}>
            <Fade dur={dur}>
              <Comp />
            </Fade>
          </Sequence>
        );
      })}
      <Progress />
    </AbsoluteFill>
  );
};

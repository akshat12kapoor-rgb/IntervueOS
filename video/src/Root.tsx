import React from "react";
import { Composition } from "remotion";
import { Walkthrough } from "./Walkthrough";
import { FPS, H, W, total } from "./theme";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Walkthrough"
    component={Walkthrough}
    durationInFrames={Math.round(total * FPS)}
    fps={FPS}
    width={W}
    height={H}
  />
);

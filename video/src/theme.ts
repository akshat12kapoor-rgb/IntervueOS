export const C = {
  bg: "#0B0C0F",
  panel: "#14161C",
  panelAlt: "#1A1D25",
  stroke: "#272B36",
  text: "#E8EAF0",
  dim: "#9AA1B4",
  faint: "#5C6377",
  blue: "#7C9CF5",
  green: "#5BD6A0",
  amber: "#E8B55B",
  red: "#F2765C",
  violet: "#B18AF0",
} as const;

export const FPS = 30;
export const W = 1920;
export const H = 1080;

/** Scene durations in seconds. Order matches Root.tsx. */
export const SCENES = {
  title: 14,
  premise: 30,
  target: 34,
  loop: 48,
  timing: 74,
  protocols: 44,
  division: 32,
  config: 40,
  local: 46,
  report: 34,
  deploy: 50,
  outro: 14,
} as const;

export const total = (Object.values(SCENES) as number[]).reduce((a, b) => a + b, 0);

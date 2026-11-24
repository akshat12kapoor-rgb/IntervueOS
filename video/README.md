# Walkthrough video

A ~7-minute technical walkthrough of IntervueOS: architecture, the three timing
paths, provider protocols, configuration, running it locally, and deployment.

Built with [Remotion](https://remotion.dev) — React components rendered to MP4.
This is documentation, not part of the running system. Nothing in `prototype/`
depends on it.

## Render it

```bash
cd video && npm install
npx remotion render Walkthrough out/intervueos-walkthrough.mp4
```

Output lands in `video/out/` (gitignored).

### If Chrome fails to download

Remotion fetches its own Chrome Headless Shell on first run. If that extraction
fails, point it at any existing Chrome-for-Testing binary:

```bash
npx remotion render Walkthrough out/intervueos-walkthrough.mp4 --browser-executable=/path/to/chrome-headless-shell
```

## Edit it

```bash
npx remotion studio
```

Scene order and durations live in `src/theme.ts` (`SCENES`); each scene is a
file under `src/scenes/`. Shared primitives are in `src/components.tsx`.

All animation is driven by `useCurrentFrame()` — CSS transitions and animations
do not render correctly in Remotion and are avoided throughout.

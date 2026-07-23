# Connor short-video Remotion package

Vertical `1080×1920` templates for daily AI shorts.

## Setup

```bash
cd short_video
npm install
```

## Studio (preview)

```bash
npm run studio -- --props=../data/short_video/2026-07-22/render_props.json
```

## Render

Prefer the Python CLI (writes props, platform copy, then invokes Remotion):

```bash
# One-shot (plan → TTS → render → quality_report.json)
python -m app.cli daily produce-short-video --date 2026-07-22
python -m app.cli daily produce-short-video --date 2026-07-22 --dry-run

# Or step-by-step
python -m app.cli daily plan-short-video --date 2026-07-22
python -m app.cli daily synthesize-short-video --date 2026-07-22
python -m app.cli daily render-short-video --date 2026-07-22
```

Manual:

```bash
npx remotion render src/index.ts ConnorDailyShort out/connor_daily_short.mp4 --props=../data/short_video/DATE/render_props.json
npx remotion still src/index.ts ConnorDailyCover out/cover.png --props=../data/short_video/DATE/render_props.json
```

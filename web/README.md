# Connor public site

Next.js 15 (App Router) + Tailwind frontend for the Connor public briefing site.

The console (`../frontend`) is separate — this app only consumes `/api/public/*`.

## Prerequisites

- Node.js 20+
- Public FastAPI API at `http://127.0.0.1:8080` (or set `CONNOR_PUBLIC_API_BASE`)

## Setup

```bash
cd web
npm install
```

## Develop

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

`next.config.ts` rewrites `/api/*` and `/media/*` to the FastAPI origin so browser requests stay same-origin.

## Production

Live site: **https://aiconnor.cn** (Cloudflare Tunnel → this Next app on `127.0.0.1:3000`).

Full runbook: [`../docs/cloudflare-tunnel.md`](../docs/cloudflare-tunnel.md).

```powershell
npm run build
npm run start -- -p 3000 -H 127.0.0.1
```

Do not serve a turbopack-contaminated `.next` with `next start`; if you see missing `[turbopack]_runtime.js`, delete `.next` and rebuild.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONNOR_PUBLIC_API_BASE` | `http://127.0.0.1:8080` | Server-side fetch origin for public API |
| `CONNOR_PUBLIC_SITE_URL` | `http://localhost:3000` | Canonical site URL (metadata / sitemap) |
| `CONNOR_PUBLIC_USE_FIXTURE` | unset | Set to `1` to load `fixtures/public-report.json` instead of the API (never used as a silent fallback) |

Example fixture mode:

```bash
# PowerShell
$env:CONNOR_PUBLIC_USE_FIXTURE="1"
npm run dev
```

## Scripts

```bash
npm run dev      # Next.js + Turbopack
npm run build    # production build
npm run start    # serve production build
npm run lint
npm test         # vitest (media gallery helper)
```

## Routes

| Path | Description |
| --- | --- |
| `/` | Published report timeline |
| `/daily/[YYYY-MM-DD]` | Full daily report |
| `/about` | Product principles |
| `/archive` | Published report timeline |

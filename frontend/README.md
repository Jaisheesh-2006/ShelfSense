# ShelfSense Dashboard

A live store-intelligence dashboard (React + Vite + TypeScript). It polls the Intelligence API
every few seconds and shows the headline **conversion rate**, the session funnel, the zone heatmap,
anomalies, and feed health — all computed live from CCTV events + POS, never hardcoded.

## Design system

A small, **flat, token-based** system ("ShelfSense UI") in plain CSS variables — no UI library, no
gradients. White-forward surfaces, one calm blue accent (`#2563eb`), one teal secondary for the
heatmap, soft semantic tints, system fonts, and tabular numbers so live values don't jitter. Tokens
live in [`src/styles/tokens.css`](src/styles/tokens.css).

## Run

```bash
npm install
npm run dev        # http://localhost:5173 (expects the API on :8000)
npm run build      # production bundle -> dist/
npm run typecheck  # tsc --noEmit
```

In Docker it's built and served by nginx (see `Dockerfile`) and comes up with the rest of the stack
via `docker compose up` at **http://localhost:8080**.

## Config

- `VITE_API_BASE` — API base URL. Defaults to `http://<current-host>:8000`, which works for both
  `localhost` and a LAN IP (the API enables CORS).
- `VITE_STORE_ID` — store to display. Defaults to `ST1008`.

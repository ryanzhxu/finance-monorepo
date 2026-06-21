# finance-monorepo web_ui

React 19 + TypeScript + Vite frontend for the analyst, screener, health, and watchlist views.

## Commands

Install dependencies:

```bash
npm install
```

Start local dev:

```bash
npm run dev
```

Build for production:

```bash
npm run build
```

Lint:

```bash
npm run lint
```

At the latest repo guidance refresh, `npm run build` passed and `npm run lint` failed on `react-hooks/set-state-in-effect` in `src/views/Analyze.tsx`.

## Environment

- `VITE_ANALYST_URL` defaults to `http://localhost:8001`
- `VITE_SCREENER_URL` defaults to `http://localhost:8002`

`web_ui/.env.local` is ignored. `web_ui/.env.production` is tracked deploy wiring.

## Notes

- The frontend talks directly to the backend through `src/api/client.ts`.
- If backend response shapes change, update `src/api/types.ts` and regenerate API artifacts from the repo root.
- Production deploys through the static `finance-web-ui` service in `render.yaml`.

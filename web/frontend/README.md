# Haqwa web frontend

React + TypeScript + Vite. The build (`dist/`) is served as static files by the FastAPI app, so there is one container and no Node in production.

## Run locally

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production build into dist/
npm run lint
```

## Mock mode vs real API

All server calls go through `src/api/client.ts`.

- Default: **mock mode**. Screen 1 uses the real Gemini outputs from spike v2.1 (`src/api/fixtures.ts`). Screens 2-3 use real `demo.run_scenario()` reports and one real `ai.explain` answer (`src/api/runFixtures.ts`). No API key or quota is needed.
- To use the FastAPI app, create `web/frontend/.env.local` with `VITE_USE_MOCK=false`.

## Layout

| Path | What |
|---|---|
| `src/api/` | C3 types, API client, mock data |
| `src/components/` | Header, policy panel, question/review cards, timeline, verdicts, AI explanation box |
| `src/screens/DefineScreen.tsx` | Screen 1: the AI interviews the policy owner |
| `src/screens/TestScreen.tsx` | Screen 2: pick a scenario, run it, see core's verdict |
| `src/screens/ResultsScreen.tsx` | Screen 3: which event broke which rule, plus an AI suggestion |
| `src/lib/words.ts` | Event names -> plain words (presentation only) |
| `src/lib/persist.ts` | Keeps progress across a refresh (sessionStorage) |

## Navigation and refresh

No router: `App.tsx` keeps the current step, the confirmed spec and the last run in React state, saved in `sessionStorage`. A refresh keeps the owner where they were; a new tab starts clean; **Start over** clears it. If a saved shape changes, bump `VERSION` in `src/lib/persist.ts`.

The web holds no business logic: rules are parsed and updated by the Python library through the API.

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

- Default: **mock mode**. The answers are the real Gemini outputs from spike v2.1 (`src/api/fixtures.ts`), so no API key or quota is needed.
- To use the FastAPI app, create `web/frontend/.env.local` with `VITE_USE_MOCK=false`.

## Layout

| Path | What |
|---|---|
| `src/api/` | C3 types, API client, mock data |
| `src/components/` | Header, policy panel, question card, review card, technical details |
| `src/screens/DefineScreen.tsx` | Screen 1: the AI interviews the policy owner |
| `src/lib/words.ts` | Event names -> plain words (presentation only) |

The web holds no business logic: rules are parsed and updated by the Python library through the API.

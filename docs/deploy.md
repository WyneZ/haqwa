# Deploying Haqwa to Cloud Run

One container, one Cloud Run service. FastAPI serves the API (`/api/v1/...`), the
health check (`/healthz`) and the built React app (everything else).

Owner: Wyne (see `docs/decisions.md`, 2026-10-09).

## What the image contains

`Dockerfile` has two stages:

1. **frontend** — `node:22-slim`, `npm ci`, `npm run build` with `VITE_USE_MOCK=false`.
2. **runtime** — `python:3.12.14-slim` + `uv`, installs only runtime dependencies from
   `uv.lock` (`uv sync --frozen --no-dev`), copies `src/`, `web/api/` and the built
   `web/frontend/dist/`, runs as a non-root user.

Start command: `uvicorn web.api.main:app --host 0.0.0.0 --port $PORT`.

| Setting | Value | Notes |
|---|---|---|
| `PORT` | set by Cloud Run (8080) | do not set it yourself |
| `GEMINI_API_KEY` | from Secret Manager | never in code, image, logs or docs |
| `HAQWA_CACHE_DIR` | `/tmp/haqwa_cache` (image default) | in-memory, lost on restart |
| `HAQWA_MODEL` | unset | optional model override |
| `HAQWA_DEV_CORS` | unset | dev only; not needed because UI and API share one origin |

The API is stateless (the browser keeps the draft in `sessionStorage`), so several
instances are safe. `--max-instances 1` is used only to cap cost.

> **Mock trap:** the frontend uses mock data unless it was built with
> `VITE_USE_MOCK=false`. The Dockerfile sets it. If you ever build the frontend another
> way, check it (see "Verify" below).

## One-time setup

All names below (`haqwa`, `gemini-api-key`, `asia-southeast1`) are the team defaults, so
both developers can follow the same steps in their own project.

1. **Project + billing.** Create a Google Cloud project, link a billing account
   (Cloud Run requires one even inside the free tier).
2. **Budget alert.** Billing → Budgets & alerts → budget of a few USD on this project with
   50/90/100 % email alerts. Alerts only notify; they do not stop spending.
3. **Enable APIs:** Cloud Run Admin, Cloud Build, Artifact Registry, Secret Manager.
4. **Gemini key (free tier).** In AI Studio, create the key in a project **without
   billing** (decision 2026-09-28: free tier only). A key from a billed project is on the
   paid tier. Check that AI Studio shows the key's tier as Free.
5. **Secret.** Secret Manager → Create secret → name `gemini-api-key`, value = the key.
6. **Secret access.** Give the Cloud Run runtime service account
   (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`) the role
   *Secret Manager Secret Accessor* on that secret. The console offers this when you
   reference the secret; the CLI is below.

CLI equivalent:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region asia-southeast1
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com

# Paste the key at the prompt; it never reaches shell history.
read -s KEY && printf "%s" "$KEY" | gcloud secrets create gemini-api-key --data-file=- && unset KEY

PROJECT_NUMBER=$(gcloud projects describe "$(gcloud config get-value project)" --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## Deploy

### Option A — CLI (from the repo root)

```bash
gcloud run deploy haqwa \
  --source . \
  --allow-unauthenticated \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi
```

`--source .` builds the Dockerfile on Cloud Build (amd64), so it works from an M-series
Mac. Do not push an image built locally on arm64; Cloud Run needs amd64.

### Option B — Console, continuous deploy from GitHub

Cloud Run → Create service → *Continuously deploy from a repository* → Set up with Cloud
Build → GitHub → `WyneZ/haqwa`, branch `^main$`, build type **Dockerfile**
(`/Dockerfile`). Then:

- Service name `haqwa`, region `asia-southeast1`
- Authentication: allow public access (judges must open it without signing in)
- Billing: request-based; autoscaling min 0, max 1
- Container: port 8080, memory 512 MiB
- Variables & Secrets → Reference a secret → env var `GEMINI_API_KEY` →
  secret `gemini-api-key`, version `latest`

Every push to `main` then rebuilds and redeploys.

## Verify (after every deploy)

1. `https://SERVICE_URL/healthz` returns `{"ok":true}`.
2. `https://SERVICE_URL/api/v1/scenarios` returns the demo scenario list.
3. Open `https://SERVICE_URL/`, enter a new rule that is not in the fixtures, and check
   the questions are about **your** rule. Fixture answers mean the mock build slipped in.
4. Run one scenario on the Test screen and see a verdict.
5. Cloud Run → `haqwa` → Logs: no tracebacks.

## Update and roll back

- Update: run Option A again, or push to `main` (Option B).
- Roll back: Cloud Run → `haqwa` → Revisions → pick the last good revision → Manage
  traffic → 100 %. CLI:
  `gcloud run services update-traffic haqwa --to-revisions REVISION_NAME=100`

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Container failed to start / did not listen on port | app not on `0.0.0.0:$PORT`, or import error at startup (check logs) |
| `Permission denied` on secret | step 6 (Secret Accessor role) missing |
| Build fails at `uv sync --frozen` | `uv.lock` out of date: run `uv lock` and commit |
| UI shows fixture answers | frontend built without `VITE_USE_MOCK=false` |
| API returns `gemini_quota` (429) | free-tier rate limit; wait, or replay recorded demo scenarios |
| `/api/...` returns the HTML page | path typo; unknown `/api/*` paths return 404, everything else is the SPA |

## Cost guardrails

- `--min-instances 0` (an always-on instance is billed while idle).
- `--max-instances 1` caps compute.
- Budget alert on the project.
- Gemini key from a project without billing.

## Two deployments

Each developer may deploy to their own project. Only **one** URL is official (submission,
deck, video); record which in `docs/decisions.md`. Keep that project alive and its billing
valid through judging. If both projects auto-deploy from `main`, a broken push breaks both,
so merge only tested code to `main`.

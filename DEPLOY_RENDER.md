# Deploy to Render

## 1) Prepare repository

- Ensure the latest code is pushed to GitHub.
- Verify `requirements.txt` includes all backend dependencies.
- Confirm the app starts locally:
  - `python run.py`

## 2) Create Web Service in Render

1. Open [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** -> **Web Service**.
3. Connect your GitHub account/repository.
4. Select branch (usually `main`).

## 3) Service settings

- **Name:** `slideforge-backend` (or your preferred name)
- **Runtime:** `Python 3`
- **Python Version:** `3.11.x` (important; do not use 3.14 for current pinned deps)
- **Build Command:**
  - `pip install -r requirements.txt`
- **Start Command:**
  - `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- **Plan:** Free/Starter (depending on your needs)

Repository also includes `runtime.txt` with `python-3.11.11`.

## 4) Environment variables

Set these in Render -> **Environment**:

- `AI_TOKEN` = your API token
- `AI_BASE_URL` = your AI gateway URL
- `LLM_MODEL` = model id used by backend

Optional:

- `PYTHONUNBUFFERED=1`
- `PYTHON_VERSION=3.11.11` (recommended to force stable build environment)
- `IMAGE_CONCURRENCY=2` (stabilizes image generation on Render)
- `IMAGE_TIMEOUT_SEC=75` (prevents jobs from hanging too long on a single image)

## 5) Persistent data (optional)

The app stores generated files in local folders (`generated`, `uploads`).
On free instances, local disk can be ephemeral. If you need persistence:

- use Render persistent disk (paid plans), or
- upload generated artifacts to object storage (S3-compatible).

## 6) Health check

After deploy, verify:

- `GET /api/health`
- `GET /create.html`

If these return OK, service is running.

## 7) Common issues

- **503 AI unavailable:** invalid token, blocked outbound network, or wrong `AI_BASE_URL`.
- **500 on planning:** check Render logs for exceptions from `backend.main`.
- **Missing static pages:** make sure frontend files are present in `frontend/` and build is from correct branch.
- **Build fails on `pydantic-core` / Rust / maturin:**
  - reason: Render built on Python 3.14 and tried compiling from source;
  - fix: set `PYTHON_VERSION=3.11.11` and redeploy with **Clear build cache & deploy**.

## 8) Auto deploy

Enable **Auto-Deploy** in Render so every push to `main` redeploys automatically.

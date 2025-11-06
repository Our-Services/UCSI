Deployment Guide
================

Prerequisites
-------------
- A server or VPS with Docker and Docker Compose installed; or a hosting that supports WSGI/Gunicorn.
- A domain with HTTPS (recommended). You can use Cloudflare Tunnel/ngrok for a quick HTTPS URL.

Environment Variables
---------------------
- `TELEGRAM_TOKEN`: Your Telegram bot token.
- `WEB_APP_URL`: Public HTTPS URL to the admin panel, e.g. `https://your-domain.com/manage` or HTTPS tunnel URL.
- `FLASK_SECRET_KEY`: A strong random string used by Flask sessions.

Docker Compose (Bot + Web)
--------------------------
1. Copy `.env.example` to `.env` and fill values.
2. Ensure `docker-compose.yml` contains both `bot` and `web` services (already added):
   - `web` shares `./config` and `./output` volumes with the bot.
   - `web` exposes port `5000` for the Flask app.
3. Start services:
   ```sh
   docker compose up -d
   ```
4. Point your reverse proxy (Caddy/Nginx) to `http://127.0.0.1:5000` and enable HTTPS on your domain.
5. Update `.env` with `WEB_APP_URL=https://YOUR-DOMAIN/manage` so the Telegram bot opens the admin panel.

WSGI Hosting (Render/Heroku/PythonAnywhere)
-------------------------------------------
1. Use `src/wsgi.py` as the entrypoint (`from src.web_app import app as application`).
2. Install dependencies from `requirements.txt`.
3. Set environment variables in the provider settings (`TELEGRAM_TOKEN`, `WEB_APP_URL`, `FLASK_SECRET_KEY`).
4. Configure HTTPS (provider managed or via custom domain).

Render One‑Click (Blueprint)
----------------------------
You can create both the web app and the Telegram worker directly from your repo using `render.yaml`.

Steps:
1. Push this repo to GitHub (done).
2. In Render dashboard: click `New` → `Blueprint` and select your `UCSI` repo.
3. Render will read `render.yaml` and show two services:
   - `ucsi-web` (Web Service)
   - `ucsi-bot` (Background Worker)
4. Click `Apply` to create them.
5. Open `ucsi-web` → `Environment` and set:
   - `WEB_APP_URL=https://<your-web-service>.onrender.com/manage`
   - `TELEGRAM_TOKEN=<your_botfather_token>` (also set this on `ucsi-bot`).
   - `FLASK_SECRET_KEY` is auto-generated; you may replace it if needed.
6. Ensure both services have `Auto Deploy` enabled (default in blueprint).
7. Test:
   - Web: open `https://<your-web-service>.onrender.com/manage`.
   - Bot: send `/start` to your bot and watch logs in `ucsi-bot`.

Notes:
- Files written to `config/config.json` are on ephemeral storage. For persistence across redeploys, consider a database or Render Disks (optional future step).
- No need to set `PORT`; Render injects it and `gunicorn` binds to `$PORT`.

Cloud Run (Serverless Webhook)
------------------------------
This option is free‑friendly because the bot uses a webhook and only runs on incoming requests.

Overview
- Create two Cloud Run services from this repo: one for the bot (webhook), one for the web app (Flask).
- The bot runs in webhook mode using `USE_WEBHOOK=1` and listens on `PORT`.
- The web app is served by `gunicorn` and uses the same image.

Prepare Container Image
- Add these commands to the build to install Playwright Chromium and its dependencies:
  - `python -m playwright install --with-deps chromium`
- If you prefer full control, use a Dockerfile like below:
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt ./
  RUN pip install --no-cache-dir -r requirements.txt \
      && python -m playwright install --with-deps chromium
  COPY . .
  ENV PYTHONUNBUFFERED=1
  # Default command can be overridden per Cloud Run service
  CMD ["gunicorn", "src.wsgi:app", "--bind", "0.0.0.0:$PORT"]
  ```

Create the Bot Service (Webhook)
1. In Google Cloud Console: enable Cloud Run and Cloud Build APIs.
2. Deploy from source (or from the Dockerfile image) to Cloud Run.
3. Set Runtime/Container command:
   - Command: `python`
   - Arguments: `-u`, `src/telegram_bot.py`
4. Set environment variables:
   - `TELEGRAM_TOKEN=<your_botfather_token>`
   - `USE_WEBHOOK=1`
   - `WEBHOOK_URL=https://<your-bot-service-url>/<WEBHOOK_PATH-or-token>`
   - Optional: `WEBHOOK_PATH=<custom-path>` (defaults to your bot token if omitted).
5. Allow unauthenticated requests and choose a region near you.
6. After deploy, copy the service URL (looks like `https://<name>-<hash>-<region>.run.app`).
   - If you did not set `WEBHOOK_PATH`, use your bot token as the path: `WEBHOOK_URL=https://<service-url>/<TELEGRAM_TOKEN>`.
7. The application will set the webhook automatically on start. Test by sending `/start` to your bot.

Create the Web App Service (Flask)
1. Deploy the same source/image to a second Cloud Run service.
2. Runtime/Container command:
   - Command: `gunicorn`
   - Arguments: `src.wsgi:app`, `--bind`, `0.0.0.0:$PORT`
3. Environment variables:
   - `FLASK_SECRET_KEY=<random-strong-string>`
   - `WEB_APP_URL=https://<your-web-service-url>/manage`
   - Optional: `TELEGRAM_TOKEN=<same token>` (for consistency if you want the web to link the bot).
4. Allow unauthenticated requests. Copy the service URL and visit `/manage`.

CLI Quick Deploy (Alternative)
If you use `gcloud`, run:
```sh
# Bot (Webhook)
gcloud run deploy ucsi-bot \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars TELEGRAM_TOKEN=YOUR_TOKEN,USE_WEBHOOK=1,WEBHOOK_URL=https://YOUR_BOT_URL/YOUR_TOKEN \
  --command python --args -u,src/telegram_bot.py

# Web App (Flask)
gcloud run deploy ucsi-web \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars FLASK_SECRET_KEY=YOUR_SECRET,WEB_APP_URL=https://YOUR_WEB_URL/manage \
  --command gunicorn --args src.wsgi:app,--bind,0.0.0.0:$PORT
```

Notes (Cloud Run)
- Cloud Run sleeps between requests; webhook instantly wakes the bot on Telegram calls.
- Storage is ephemeral. `config/config.json` is not persistent across image rebuilds; use a database or re‑provide config each deploy.
- Playwright requires Chromium and system deps; ensure the build step installs them as shown.

Quick HTTPS Tunnel (No Server)
------------------------------
1. Run Flask locally, bind to all interfaces:
   ```sh
   python src/web_app.py
   ```
2. Create an HTTPS tunnel (Cloudflare Tunnel/ngrok) to port `5000`.
3. Set `WEB_APP_URL` to the tunnel URL + `/manage`.

Data Sharing
------------
- Both bot and web app read/write `config/config.json`. Keep them on the same machine or provide a shared storage to ensure synchronization.

Validation Checklist
--------------------
- Open `https://YOUR-DOMAIN/manage`, log in as admin, and perform user edits.
- In Telegram, use the admin flow; the “Open Admin Panel” button should open the WebApp when `WEB_APP_URL` is HTTPS.
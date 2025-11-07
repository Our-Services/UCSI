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

Render (Free) — Web Admin Panel
--------------------------------
This repo includes a `render.yaml` for one‑click deploy of the Flask admin panel.

Steps:
- Push this project to a Git repository (GitHub/GitLab).
- Create a free account on Render and click “New +” → “Blueprint”.
- Point to your repo; Render will detect `render.yaml` and create a Web Service.
- Set environment variables:
  - `FLASK_SECRET_KEY`: any strong random string.
  - `WEB_APP_URL`: your Render URL + `/manage` (e.g. `https://ucsi-web.onrender.com/manage`).
  - `TELEGRAM_TOKEN`: only needed if you plan to send notifications from the web to Telegram.
- Deploy. The service listens on `/$` for redirect to `/manage` and health check at `/status`.

Notes:
- The Telegram bot (`src/telegram_bot.py`) is not part of this web service. If you also want the bot online 24/7, deploy a second service (Docker or Python) that runs `python -u src/telegram_bot.py` and shares the same `config/` and `output/` storage.
- Playwright browsers are heavy; keep automation on your PC/server if free tier resources are limited. The admin panel will work fine without running automation on the same host.

 Minimal dependencies on Render
 ------------------------------
- To avoid build failures on Render Free (e.g., `greenlet` compiling via `playwright`), the web service installs only `Flask`, `gunicorn`, and `python-dotenv` via `render.yaml`.
- This is sufficient for the admin panel. Bot/automation dependencies remain in `requirements.txt` for local or worker deployment.
- If you decide to run the bot as a separate Background Worker on Render, use a Docker-based worker or a host with system build tools enabled.

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
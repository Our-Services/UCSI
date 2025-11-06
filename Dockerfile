# Minimal image to run the Telegram bot 24/7
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for better caching
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install -r /app/requirements.txt \
    && python -m playwright install --with-deps chromium

# Copy application code
COPY src /app/src
COPY config /app/config

# Create output directory (can be mounted as a volume)
RUN mkdir -p /app/output

# Runtime env variables used by the bot
# Set TELEGRAM_TOKEN at runtime via environment

CMD ["python", "-u", "src/telegram_bot.py"]
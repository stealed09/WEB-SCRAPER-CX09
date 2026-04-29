# Railway Dockerfile for WEB-SCRAPER-CX09
# Uses Playwright + Chromium for JS-challenge bypass (wuaze/InfinityFree)

FROM python:3.11-slim

# Install Chromium system dependencies
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    # Chromium core deps
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 \
    libxshmfence1 libgles2 \
    fonts-liberation fonts-noto-color-emoji \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright + Chromium browser
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy app
COPY . .

CMD ["python", "bot.py"]

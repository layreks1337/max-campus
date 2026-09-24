# ── Сборка фронтенда ──────────────────────────────────────────────
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build


# ── Бэкенд ────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Кириллица в логах и в strftime без этого падает на несовместимой локали
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./backend/pyproject.toml
RUN pip install --upgrade pip && pip install \
      "fastapi>=0.115" "uvicorn[standard]>=0.32" "sqlalchemy[asyncio]>=2.0.36" \
      "asyncpg>=0.30" "pgvector>=0.3.6" "pydantic>=2.9" "pydantic-settings>=2.6" \
      "httpx>=0.27" "python-multipart>=0.0.12" "fpdf2>=2.8" "qrcode[pil]>=8.0" \
      "openai>=1.54" "python-dateutil>=2.9"

# Корневые сертификаты Минцифры — без них TLS до platform-api2.max.ru не поднимется
COPY certs/ ./certs/
COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist

ENV PYTHONPATH=/app/backend \
    DATA_DIR=/data

RUN mkdir -p /data/documents /data/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend"]

# ── Сборка фронтенда ──────────────────────────────────────────────
FROM node:22-alpine AS frontend

WORKDIR /build
# Строго по закоммиченному package-lock.json: без него или при расхождении
# с package.json npm ci падает, а не подбирает версии заново
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
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

# Системных пакетов не ставим: curl в контейнере не нужен (healthcheck в
# docker-compose.yml — на Python), ca-certificates уже есть в базовом образе.
# Версии Python-пакетов зафиксированы в requirements.txt вместе с транзитивными:
# чистая сборка даёт тот же набор, что проверен смоуком.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --disable-pip-version-check --root-user-action=ignore \
      -r backend/requirements.txt

# Корневые сертификаты Минцифры — без них TLS до platform-api2.max.ru не поднимется
COPY certs/ ./certs/
COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist

ENV PYTHONPATH=/app/backend \
    DATA_DIR=/data

RUN mkdir -p /data/documents /data/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend"]

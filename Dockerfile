# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-build

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLM_PROVIDER=mock \
    BI_DATA_DIR=/data \
    CATALOG_DB_PATH=/data/catalog.db \
    CHAT_DB_PATH=/data/chats.db

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN groupadd --system evia \
    && useradd --system --gid evia --home-dir /app --shell /usr/sbin/nologin evia \
    && mkdir -p /data \
    && chown -R evia:evia /app /data

USER evia

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

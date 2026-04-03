FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/v_sentinel.db

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libturbojpeg0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md README_zh.md /app/
COPY backend /app/backend
COPY core /app/core
COPY frontend /app/frontend
COPY docs /app/docs
COPY scripts /app/scripts

COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]

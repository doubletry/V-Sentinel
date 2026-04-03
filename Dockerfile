FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""
ARG http_proxy=""
ARG https_proxy=""
ARG no_proxy=""

COPY frontend/package.json ./
RUN HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" NO_PROXY="${NO_PROXY}" \
    http_proxy="${http_proxy}" https_proxy="${https_proxy}" no_proxy="${no_proxy}" \
    npm install

COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""
ARG http_proxy=""
ARG https_proxy=""
ARG no_proxy=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/v_sentinel.db

RUN HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" NO_PROXY="${NO_PROXY}" \
    http_proxy="${http_proxy}" https_proxy="${https_proxy}" no_proxy="${no_proxy}" \
    apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libturbojpeg0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md README_zh.md /app/
COPY backend /app/backend
COPY core /app/core
COPY frontend /app/frontend
COPY docs /app/docs
COPY scripts /app/scripts

COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

RUN HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" NO_PROXY="${NO_PROXY}" \
    http_proxy="${http_proxy}" https_proxy="${https_proxy}" no_proxy="${no_proxy}" \
    pip install --no-cache-dir .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]

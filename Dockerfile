# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

ARG RELAX_HTTPS_VERIFICATION=false

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""
ARG http_proxy=""
ARG https_proxy=""
ARG no_proxy=""

COPY frontend/package.json ./
RUN --mount=type=secret,id=build_proxy_ca,required=false \
    if [ "${RELAX_HTTPS_VERIFICATION}" = "true" ]; then \
        export NODE_TLS_REJECT_UNAUTHORIZED=0 npm_config_strict_ssl=false NPM_CONFIG_STRICT_SSL=false; \
    fi; \
    if [ -f /run/secrets/build_proxy_ca ]; then \
        export NODE_EXTRA_CA_CERTS=/run/secrets/build_proxy_ca NPM_CONFIG_CAFILE=/run/secrets/build_proxy_ca; \
    fi; \
    npm install

COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

ARG RELAX_HTTPS_VERIFICATION=false

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""
ARG http_proxy=""
ARG https_proxy=""
ARG no_proxy=""

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

RUN --mount=type=secret,id=build_proxy_ca,required=false \
    set -- pip install --no-cache-dir; \
    if [ "${RELAX_HTTPS_VERIFICATION}" = "true" ]; then \
        export PYTHONHTTPSVERIFY=0; \
        set -- "$@" --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org; \
    fi; \
    if [ -f /run/secrets/build_proxy_ca ]; then \
        export PIP_CERT=/run/secrets/build_proxy_ca REQUESTS_CA_BUNDLE=/run/secrets/build_proxy_ca SSL_CERT_FILE=/run/secrets/build_proxy_ca; \
    fi; \
    "$@" .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]

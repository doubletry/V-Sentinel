# Docker Deployment

## Build

```bash
./scripts/build_docker.sh
```

The build script automatically reads the current shell proxy settings (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, and their lowercase variants) and passes them to `docker build` only for the image build. If the detected proxy host is `127.0.0.1` / `localhost`, it is rewritten to `host.docker.internal` for Docker build networking.

When an HTTPS proxy is present:

- set `RELAX_HTTPS_VERIFICATION=true ./scripts/build_docker.sh` if you need npm / pip to relax HTTPS validation behind a self-signed interception proxy
- leave `RELAX_HTTPS_VERIFICATION` unset to keep normal HTTPS verification
- the relaxed mode is a build-time-only compatibility fallback for trusted internal networks, because it reduces HTTPS verification for npm / pip dependency downloads

If the shell also exposes a readable PEM CA file path (`BUILD_CA_CERT`, `NODE_EXTRA_CA_CERTS`, `NPM_CONFIG_CAFILE`, `PIP_CERT`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, or `SSL_CERT_FILE`), that certificate is mounted into the build as an additional fallback.

You can override the image name or tag:

```bash
IMAGE_NAME=my-registry/v-sentinel IMAGE_TAG=2026.04.03 ./scripts/build_docker.sh
```

## Run

The application is packaged as a **single container**. It serves the built frontend, the REST API, the WebSocket endpoint, and the persisted message thumbnails from the same process.

```bash
docker run -d \
  --name v-sentinel \
  -p 8000:8000 \
  -e BACKEND_PORT=8000 \
  -e DB_PATH=/app/data/v_sentinel.db \
  -v "$(pwd)/data:/app/data" \
  v-sentinel:latest
```

## Exposed interface

- `8000/tcp`: frontend + REST API + WebSocket + persisted message thumbnails

## Persistent data

Mount `/app/data` so the following are retained:

- `v_sentinel.db`
- `message_thumbnails/`

Message thumbnails are written to the filesystem and are no longer stored inside SQLite.

## External services

This container does **not** start MediaMTX or any other sidecar service.

- If you need the 视频墙 page to play live video, configure an external RTSP/WebRTC gateway in the Settings page.
- If you need AI inference, configure the V-Engine service addresses in the Settings page.
- If you need daily-summary email delivery, configure the email service in the Settings page.

## Upgrade

```bash
docker pull <your-image>
docker stop v-sentinel
docker rm v-sentinel
docker run -d \
  --name v-sentinel \
  -p 8000:8000 \
  -e BACKEND_PORT=8000 \
  -e DB_PATH=/app/data/v_sentinel.db \
  -v "$(pwd)/data:/app/data" \
  <your-image>
```

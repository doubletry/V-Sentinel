#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-v-sentinel}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKER_BIN="${DOCKER_BIN:-docker}"

build_args=()
extra_args=()

# Return the first non-empty proxy-related value from a list of candidates.
first_non_empty() {
  local value
  for value in "$@"; do
    if [[ -n "${value:-}" ]]; then
      printf '%s' "$value"
      return 0
    fi
  done
  return 0
}

# Rewrite localhost/127.0.0.1 proxy URLs to host.docker.internal for Docker builds.
rewrite_proxy_host() {
  PROXY_VALUE="$1" python - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit

value = os.environ.get("PROXY_VALUE", "").strip()
if not value:
    raise SystemExit(0)

parts = urlsplit(value)
hostname = parts.hostname or ""
if hostname not in {"127.0.0.1", "localhost"}:
    print(value)
    raise SystemExit(0)

netloc = parts.netloc
if "@" in netloc:
    userinfo, hostport = netloc.rsplit("@", 1)
    prefix = f"{userinfo}@"
else:
    prefix = ""
    hostport = netloc

if ":" in hostport:
    _, port = hostport.rsplit(":", 1)
    rewritten = f"{prefix}host.docker.internal:{port}"
else:
    rewritten = f"{prefix}host.docker.internal"

print(urlunsplit((parts.scheme, rewritten, parts.path, parts.query, parts.fragment)))
PY
}

HTTP_PROXY_VALUE="$(first_non_empty "${HTTP_PROXY:-}" "${http_proxy:-}")"
HTTPS_PROXY_VALUE="$(first_non_empty "${HTTPS_PROXY:-}" "${https_proxy:-}" "$HTTP_PROXY_VALUE")"
NO_PROXY_VALUE="$(first_non_empty "${NO_PROXY:-}" "${no_proxy:-}")"

needs_host_gateway=false
if [[ -n "$HTTP_PROXY_VALUE" ]]; then
  rewritten="$(rewrite_proxy_host "$HTTP_PROXY_VALUE")"
  if [[ "$rewritten" != "$HTTP_PROXY_VALUE" ]]; then
    needs_host_gateway=true
    HTTP_PROXY_VALUE="$rewritten"
  fi
fi

if [[ -n "$HTTPS_PROXY_VALUE" ]]; then
  rewritten="$(rewrite_proxy_host "$HTTPS_PROXY_VALUE")"
  if [[ "$rewritten" != "$HTTPS_PROXY_VALUE" ]]; then
    needs_host_gateway=true
    HTTPS_PROXY_VALUE="$rewritten"
  fi
fi

if [[ "$needs_host_gateway" = true ]]; then
  extra_args+=(--add-host=host.docker.internal:host-gateway)
fi

for key in HTTP_PROXY http_proxy; do
  if [[ -n "$HTTP_PROXY_VALUE" ]]; then
    build_args+=(--build-arg "${key}=${HTTP_PROXY_VALUE}")
  fi
done

for key in HTTPS_PROXY https_proxy; do
  if [[ -n "$HTTPS_PROXY_VALUE" ]]; then
    build_args+=(--build-arg "${key}=${HTTPS_PROXY_VALUE}")
  fi
done

for key in NO_PROXY no_proxy; do
  if [[ -n "$NO_PROXY_VALUE" ]]; then
    build_args+=(--build-arg "${key}=${NO_PROXY_VALUE}")
  fi
done

docker_cmd=("${DOCKER_BIN}" build)
if [[ ${#extra_args[@]} -gt 0 ]]; then
  docker_cmd+=("${extra_args[@]}")
fi
if [[ ${#build_args[@]} -gt 0 ]]; then
  docker_cmd+=("${build_args[@]}")
fi
docker_cmd+=(-t "${IMAGE_NAME}:${IMAGE_TAG}" .)

"${docker_cmd[@]}"

#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and fill it in." >&2
  exit 1
fi

set -a
. ./.env
set +a

: "${NS_HOST:?Set NS_HOST in .env (for example https://your-site.example.com)}"
NS_HOST="${NS_HOST%/}"

sha1() {
  if command -v sha1sum >/dev/null 2>&1; then
    sha1sum | awk '{print $1}'
  else
    shasum -a 1 | awk '{print $1}'
  fi
}

if [ -n "${NS_API_SECRET:-}" ]; then
  if printf '%s' "$NS_API_SECRET" | grep -Eqi '^[a-f0-9]{40}$'; then
    NS_API_SECRET_HASH="$NS_API_SECRET"
  else
    NS_API_SECRET_HASH="$(printf '%s' "$NS_API_SECRET" | sha1)"
  fi
fi

if [ -n "${NS_API_SECRET:-}" ] && [ -n "${NS_TOKEN:-}" ]; then
  echo "Both NS_API_SECRET and NS_TOKEN are set. The container will use the API secret." >&2
fi

ENGINE="${CONTAINER_ENGINE:-}"
if [ -z "$ENGINE" ]; then
  if command -v docker >/dev/null 2>&1; then
    ENGINE=docker
  elif command -v podman >/dev/null 2>&1; then
    ENGINE=podman
  else
    echo "Install Docker or Podman first." >&2
    exit 1
  fi
fi
command -v "$ENGINE" >/dev/null 2>&1 || {
  echo "Container engine '$ENGINE' was not found." >&2
  exit 1
}

BASE_IMAGE="${BASE_IMAGE:-docker.io/houthacker42/nightscout-autotune:latest}"
IMAGE="${IMAGE:-nightscout-autotune-tz:latest}"
DAYS="${AUTOTUNE_DAYS:-6}"
UAM="${UAM_AS_BASAL:-false}"
TZ_VALUE="${TZ:-Etc/UTC}"
HTML="${HTML_EXPORT:-true}"

if [ "${REBUILD_IMAGE:-false}" = "true" ] || ! "$ENGINE" image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building local image $IMAGE (adds timezone data to the upstream image)..."
  "$ENGINE" build --build-arg "BASE_IMAGE=$BASE_IMAGE" -t "$IMAGE" .
fi

VOLUME_SUFFIX=""
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null || true)" != "Disabled" ]; then
  VOLUME_SUFFIX=":Z"
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nightscout-autotune.XXXXXX")"
cleanup() {
  if [ "${KEEP_TEMP:-false}" = "true" ]; then
    echo "Kept raw run data in: $TMP_DIR"
    return
  fi
  case "$TMP_DIR" in
    /tmp/*|"${TMPDIR:-/tmp}"/*) rm -r "$TMP_DIR" ;;
    *) echo "Refusing to remove unexpected temp path: $TMP_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

mkdir -p reports
RUN_LOG="reports/last-run.log"

ARGS=(
  run --rm
  -v "$TMP_DIR:/tmp/autotune$VOLUME_SUFFIX"
  -e "NS_HOST=$NS_HOST"
  -e "AUTOTUNE_DAYS=$DAYS"
  -e "UAM_AS_BASAL=$UAM"
  -e "HTML_EXPORT=$HTML"
  -e "TZ=$TZ_VALUE"
)

[ -n "${NS_API_SECRET_HASH:-}" ] && ARGS+=(-e "NS_API_SECRET=$NS_API_SECRET_HASH")
[ -n "${NS_TOKEN:-}" ] && ARGS+=(-e "NS_TOKEN=$NS_TOKEN")
[ -n "${NS_PROFILE:-}" ] && ARGS+=(-e "NS_PROFILE=$NS_PROFILE")
[ -n "${MIN_5MIN_CARBIMPACT:-}" ] && ARGS+=(-e "MIN_5MIN_CARBIMPACT=$MIN_5MIN_CARBIMPACT")
[ -n "${AUTOSENS_MIN:-}" ] && ARGS+=(-e "AUTOSENS_MIN=$AUTOSENS_MIN")
[ -n "${AUTOSENS_MAX:-}" ] && ARGS+=(-e "AUTOSENS_MAX=$AUTOSENS_MAX")
[ -n "${INSULIN_TYPE:-}" ] && ARGS+=(-e "INSULIN_TYPE=$INSULIN_TYPE")
[ -n "${CONTAINER_NETWORK:-}" ] && ARGS+=(--network "$CONTAINER_NETWORK")

echo "Running Autotune for $DAYS day(s) against $NS_HOST ..."
echo

set +e
"$ENGINE" "${ARGS[@]}" "$IMAGE" 2>&1 \
  | sed -E \
      -e 's/(passhprase:[[:space:]]*).*/\1[redacted]/I' \
      -e 's/(token:[[:space:]]*).*/\1[redacted]/I' \
  | tee "$RUN_LOG"
STATUS=${PIPESTATUS[0]}
set -e

if [ "$STATUS" -ne 0 ]; then
  echo
  echo "Autotune failed (exit $STATUS). See $RUN_LOG and the output above." >&2
  exit "$STATUS"
fi

cp "$TMP_DIR/autotune/autotune_recommendations.html" reports/autotune_recommendations.html 2>/dev/null || true
cp "$TMP_DIR/autotune/autotune_recommendations.log" reports/autotune_recommendations.log 2>/dev/null || true
cp "$TMP_DIR/autotune/profile.json" reports/tuned-profile.json 2>/dev/null || true

echo
echo "Done."
if [ -s reports/autotune_recommendations.html ]; then
  echo "  HTML report: reports/autotune_recommendations.html"
fi
if [ -s reports/autotune_recommendations.log ]; then
  echo "  Text report: reports/autotune_recommendations.log"
fi
if [ -s reports/tuned-profile.json ]; then
  echo "  Tuned profile: reports/tuned-profile.json"
fi

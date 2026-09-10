#!/usr/bin/env bash
#
# AVR-25D — build, ship and restart the production stack.
#
#     ./deploy/push.sh backend      rebuild + ship the FastAPI image
#     ./deploy/push.sh frontend     rebuild + ship the Next.js image
#     ./deploy/push.sh all          both
#     ./deploy/push.sh config       Caddyfile / compose / .env only, no rebuild
#     ./deploy/push.sh verify       run the smoke tests against production
#
# Why this script exists
# ----------------------
# The frontend bakes NEXT_PUBLIC_* into its JS bundle at BUILD time, so a
# deploy is "docker build with seven --build-arg flags copied by hand". On
# 10 Sep 2026 that produced a production site whose Firebase key was
# '"AIza..."' -- quotes included -- because deploy/.env quoted its values and
# Compose passes quotes through where Next's own dotenv strips them. Login was
# dead and every container looked healthy.
#
# So: one parser reads .env, strips quotes, and generates the build args. The
# built image is then grepped for the values it should contain, and the upload
# is refused if they are missing. The failure mode above cannot reach the VM.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/deploy/.env"
PLATFORM="linux/arm64"          # EC2 t4g.small is Graviton (aarch64)
REMOTE_DIR="avr25d/deploy"

BE_IMAGE="avr25d-backend:prod-arm64"
FE_IMAGE="avr25d-frontend:prod-arm64"

# ── output ────────────────────────────────────────────────────────────────
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'
else B=""; G=""; R=""; Y=""; N=""; fi
step() { printf "\n%s==> %s%s\n" "$B" "$*" "$N"; }
ok()   { printf "    %s✓%s %s\n" "$G" "$N" "$*"; }
warn() { printf "    %s!%s %s\n" "$Y" "$N" "$*"; }
die()  { printf "\n%sFAILED:%s %s\n\n" "$R" "$N" "$*" >&2; exit 1; }

# ── 1. load and validate the environment ──────────────────────────────────
# Values are read with a parser that strips surrounding quotes, because that
# is the difference between Next's dotenv and Compose's interpolation, and it
# is the whole reason this script exists.
load_env() {
  [ -f "$ENV_FILE" ] || die "$ENV_FILE not found. Copy deploy/.env.example and fill it in."
  QUOTED_KEYS=""

  while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"                 # ltrim
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    # Strip one matching pair of surrounding quotes -- THE fix. Announced
    # rather than done silently: a quoted .env still works everywhere else
    # (Next strips them too), so the author should be told their file is
    # malformed instead of discovering it the next time something reads it
    # with a parser that does not strip.
    case "$val" in
      \"*\") val="${val#\"}"; val="${val%\"}"; QUOTED_KEYS="$QUOTED_KEYS $key" ;;
      \'*\') val="${val#\'}"; val="${val%\'}"; QUOTED_KEYS="$QUOTED_KEYS $key" ;;
    esac
    export "$key=$val"
  done < "$ENV_FILE"

  : "${DOMAIN:?DOMAIN is empty in deploy/.env}"
  : "${DEPLOY_HOST:=3.6.221.248}"
  : "${DEPLOY_USER:=ubuntu}"
  : "${DEPLOY_KEY:=$HOME/.ssh/nexa-drdo.pem}"
  export DOMAIN DEPLOY_HOST DEPLOY_USER DEPLOY_KEY
  WS_URL="wss://${DOMAIN}/stream"

  [ -f "$DEPLOY_KEY" ] || die "SSH key not found: $DEPLOY_KEY"
  if [ -n "$QUOTED_KEYS" ]; then
    warn "these values are quoted in deploy/.env; stripped for the build:"
    for k in $QUOTED_KEYS; do printf "        %s\n" "$k"; done
    warn "remove the quotes from deploy/.env -- Compose passes them through literally"
  fi
  ok "domain    $DOMAIN"
  ok "target    ${DEPLOY_USER}@${DEPLOY_HOST}"
  ok "ws url    $WS_URL"
}

# Every NEXT_PUBLIC_* the frontend needs. Missing or quoted values are fatal
# here rather than mysterious in the browser an hour later.
FE_VARS=(NEXT_PUBLIC_FIREBASE_API_KEY NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
         NEXT_PUBLIC_FIREBASE_PROJECT_ID NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET
         NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID NEXT_PUBLIC_FIREBASE_APP_ID)

check_fe_env() {
  local missing=0
  for v in "${FE_VARS[@]}"; do
    local val="${!v-}"
    [ -z "$val" ] && { warn "$v is EMPTY"; missing=1; continue; }
    case "$val" in
      \"*|\'*|*\"|*\') die "$v still contains quote characters after parsing. Fix deploy/.env." ;;
    esac
  done
  [ "$missing" -eq 0 ] || die "fill the missing NEXT_PUBLIC_* values in deploy/.env"
  # A Firebase web API key is 39 chars starting AIza. Cheap sanity check that
  # would have caught the 41-char quoted value immediately.
  case "$NEXT_PUBLIC_FIREBASE_API_KEY" in
    AIza*) [ ${#NEXT_PUBLIC_FIREBASE_API_KEY} -eq 39 ] \
             || warn "API key is ${#NEXT_PUBLIC_FIREBASE_API_KEY} chars (expected 39)" ;;
    *) warn "API key does not start with 'AIza' -- is it right?" ;;
  esac
  ok "all ${#FE_VARS[@]} NEXT_PUBLIC_* values present and unquoted"
}

ssh_do() { ssh -i "$DEPLOY_KEY" -o StrictHostKeyChecking=accept-new \
               -o ConnectTimeout=20 "${DEPLOY_USER}@${DEPLOY_HOST}" "$@"; }

# ── 2. build ──────────────────────────────────────────────────────────────
build_backend() {
  step "Building backend ($PLATFORM)"
  docker build --platform "$PLATFORM" \
    -f "$REPO_ROOT/deploy/Dockerfile.backend" \
    -t "$BE_IMAGE" "$REPO_ROOT" || die "backend build failed"
  ok "built $BE_IMAGE"
}

build_frontend() {
  step "Building frontend ($PLATFORM)"
  check_fe_env
  local args=(--build-arg "NEXT_PUBLIC_WS_URL=$WS_URL")
  for v in "${FE_VARS[@]}"; do args+=(--build-arg "$v=${!v}"); done
  docker build --platform "$PLATFORM" \
    -f "$REPO_ROOT/deploy/Dockerfile.frontend" \
    "${args[@]}" -t "$FE_IMAGE" "$REPO_ROOT/frontend" || die "frontend build failed"
  ok "built $FE_IMAGE"
}

# ── 3. verify the image BEFORE it leaves this machine ─────────────────────
# Greps the compiled bundle for what must be in it. This is the gate that the
# 10 Sep quoted-key bug would have hit.
verify_frontend_image() {
  step "Verifying frontend bundle"
  local key="$NEXT_PUBLIC_FIREBASE_API_KEY"

  docker run --rm --entrypoint sh -e K="$key" -e W="$WS_URL" "$FE_IMAGE" -c '
    set -e
    grep -rq "$W" .next/static || { echo "MISSING_WS"; exit 1; }
    f=$(grep -rl "$K" .next/static | head -1) || { echo "MISSING_KEY"; exit 1; }
    # the key must sit in a plain JS string: apiKey:"AIza..."  not  apiKey:%s"AIza..."%s
    grep -q "apiKey:\"$K\"" "$f" || { echo "KEY_NOT_CLEAN"; exit 1; }
    echo OK
  ' >/tmp/avr_verify 2>&1 || {
      case "$(cat /tmp/avr_verify)" in
        *MISSING_WS*)   die "bundle does not contain $WS_URL -- build args did not reach the build" ;;
        *MISSING_KEY*)  die "bundle does not contain the Firebase API key" ;;
        *KEY_NOT_CLEAN*) die "apiKey is not a clean JS string (quotes leaked in again). Check deploy/.env." ;;
        *) die "bundle verification failed: $(cat /tmp/avr_verify)" ;;
      esac; }
  ok "bundle contains $WS_URL"
  ok "apiKey is a clean, unquoted JS string"
}

# ── 4. ship ───────────────────────────────────────────────────────────────
# Streamed straight into `docker load` on the far end: no temp file here, no
# tarball left on the VM's 30 GB disk.
ship() {
  local image="$1"
  step "Shipping $image"
  local size; size=$(docker image inspect "$image" --format '{{.Size}}' 2>/dev/null || echo 0)
  printf "    %s MB uncompressed, streaming compressed...\n" "$((size/1000000))"
  docker save "$image" | gzip -1 | ssh_do 'docker load' | sed 's/^/    /' \
    || die "transfer failed"
  ok "loaded on ${DEPLOY_HOST}"
}

push_config() {
  step "Shipping deploy config"
  scp -i "$DEPLOY_KEY" -q \
     "$REPO_ROOT/deploy/docker-compose.yml" \
     "$REPO_ROOT/deploy/Caddyfile" \
     "$REPO_ROOT/deploy/.env" \
     "${DEPLOY_USER}@${DEPLOY_HOST}:~/${REMOTE_DIR}/" || die "config transfer failed"
  ssh_do "chmod 600 ~/${REMOTE_DIR}/.env"
  ok "docker-compose.yml, Caddyfile, .env"
}

recreate() {
  local svc="$1"
  step "Recreating $svc"
  ssh_do "cd ~/${REMOTE_DIR} && docker compose up -d --force-recreate $svc" 2>&1 \
    | sed 's/^/    /'
  ok "$svc recreated"
}

# ── 5. prove it actually works ────────────────────────────────────────────
smoke() {
  step "Smoke tests against https://${DOMAIN}"
  sleep 8

  local code
  code=$(curl -s -o /tmp/avr_health -m 20 -w '%{http_code}' "https://${DOMAIN}/health") || true
  [ "$code" = "200" ] && ok "/health $(cat /tmp/avr_health)" || die "/health returned $code"

  code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "https://${DOMAIN}/") || true
  [ "$code" = "200" ] && ok "/ returns 200" || die "/ returned $code"

  code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "https://${DOMAIN}/dashboard") || true
  [ "$code" = "307" ] && ok "/dashboard 307 (auth gate active)" \
                      || warn "/dashboard returned $code (expected 307)"

  # A real binary frame over wss:// -- the only test that proves the stream.
  local py="${REPO_ROOT}/backend/.venv/bin/python"
  if [ -x "$py" ]; then
    DOMAIN="$DOMAIN" "$py" - <<'PY' || die "wss:// stream test failed"
import asyncio, os, ssl, sys
try: import certifi, websockets
except ImportError: print("    ! websockets/certifi absent, skipping stream test"); sys.exit(0)
async def main():
    ctx=ssl.create_default_context(cafile=certifi.where())
    url=f"wss://{os.environ['DOMAIN']}/stream"
    async with websockets.connect(url, max_size=None, ssl=ctx) as ws:
        exts=[str(e) for e in ws.protocol.extensions]
        d=any('permessagedeflate' in e.lower().replace('-','') for e in exts)
        raw=await asyncio.wait_for(ws.recv(), timeout=30)
        assert isinstance(raw,(bytes,bytearray)) and len(raw)>1000, "not a binary frame"
        print(f"    OK wss:// delivered {len(raw)/1e6:.2f} MB binary frame")
        print(f"    OK deflate {'active' if d else 'INACTIVE'}")
asyncio.run(main())
PY
  else
    warn "backend/.venv missing -- skipped the wss:// test"
  fi
}

usage() { sed -n '3,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

# ── main ──────────────────────────────────────────────────────────────────
TARGET="${1:-}"
[ -z "$TARGET" ] && usage

step "Loading $ENV_FILE"
load_env

case "$TARGET" in
  backend)  build_backend; push_config; ship "$BE_IMAGE"; recreate backend; smoke ;;
  frontend) build_frontend; verify_frontend_image; push_config; ship "$FE_IMAGE"; recreate frontend; smoke ;;
  all)      build_backend; build_frontend; verify_frontend_image; push_config
            ship "$BE_IMAGE"; ship "$FE_IMAGE"
            recreate backend; recreate frontend; smoke ;;
  config)   push_config; ssh_do "cd ~/${REMOTE_DIR} && docker compose up -d" 2>&1 | sed 's/^/    /'; smoke ;;
  verify)   smoke ;;
  *)        usage ;;
esac

printf "\n%s✓ %s deployed — https://%s%s\n\n" "$G" "$TARGET" "$DOMAIN" "$N"

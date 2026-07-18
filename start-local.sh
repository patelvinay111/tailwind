#!/usr/bin/env bash
#
# One command to run Tailwind locally with a public Cloudflare tunnel and point
# the Vocal Bridge agent at it. Safe to re-run — it restarts cleanly each time.
#
#   ./start-local.sh          # start app + tunnel, update .env, reconfigure agent
#   ./stop-local.sh           # stop them
#
# Requires: cloudflared (brew install cloudflared).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8787}"
APP_LOG="/tmp/tailwind-app.log"
TUN_LOG="/tmp/tailwind-tunnel.log"

log() { printf "\033[1;36m▸ %s\033[0m\n" "$1"; }
die() { printf "\033[1;31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

command -v cloudflared >/dev/null 2>&1 || die "cloudflared not found — run: brew install cloudflared"

# 0. venv + deps
./run.sh setup >/dev/null

# 1. (re)start the app
pkill -f "uvicorn main:app" 2>/dev/null || true
log "Starting app on :$PORT"
nohup .venv/bin/uvicorn main:app --host 0.0.0.0 --port "$PORT" >"$APP_LOG" 2>&1 &

# 2. (re)start the tunnel
pkill -f "cloudflared tunnel" 2>/dev/null || true
: > "$TUN_LOG"
log "Starting Cloudflare tunnel"
nohup cloudflared tunnel --url "http://localhost:$PORT" >"$TUN_LOG" 2>&1 &

# 3. wait for the public URL to appear in the tunnel log
log "Waiting for public URL..."
URL=""
for _ in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUN_LOG" | head -1 || true)
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || die "Tunnel URL not found — check $TUN_LOG"
log "Public URL: $URL"

# 4. write it into .env (PUBLIC_BASE_URL)
if grep -q '^PUBLIC_BASE_URL=' .env; then
  tmp=$(mktemp); sed "s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=$URL#" .env >"$tmp" && mv "$tmp" .env
else
  echo "PUBLIC_BASE_URL=$URL" >> .env
fi
log "Updated .env PUBLIC_BASE_URL"

# 5. point the Vocal Bridge agent's tools at the new URL
log "Reconfiguring Vocal Bridge agent -> $URL"
.venv/bin/python vb/configure-agent.py "$URL" || printf "\033[1;33m  (agent reconfigure skipped/failed — check VB key + agent id in .env)\033[0m\n"

# 6. summary
printf "\n\033[1;32m✈  Tailwind is running locally\033[0m\n"
printf "   Local UI   : http://localhost:%s\n" "$PORT"
printf "   Public URL : %s\n\n" "$URL"
printf "   Logs: app=%s  tunnel=%s\n" "$APP_LOG" "$TUN_LOG"
printf "   Stop: ./stop-local.sh\n\n"

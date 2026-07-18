#!/usr/bin/env bash
#
# Tailwind AI — one command to set up the environment and run the app.
# Safe to run every time: it only does setup work that's actually needed.
#
#   ./run.sh              # setup (if needed) + start the server
#   ./run.sh setup        # setup only, don't start
#   PORT=9000 ./run.sh    # run on a different port (default 8787)
#
# Default port is 8787 (non-standard on purpose) so it won't collide with
# teammates' POCs that use the usual 8000 / 8080 / 3000.
#
set -euo pipefail
cd "$(dirname "$0")"

# This project targets Python 3.13. Override with e.g. PYTHON=python3.13 ./run.sh
MIN_MAJOR=3
MIN_MINOR=13
VENV=".venv"
PORT="${PORT:-8787}"

log() { printf "\033[1;36m▸ %s\033[0m\n" "$1"; }
die() { printf "\033[1;31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

# 0. Preflight: find a Python >= 3.13 --------------------------------------
# Honor an explicit $PYTHON, else prefer python3.13, else any python3 >= 3.13.
is_ok() {
  command -v "$1" >/dev/null 2>&1 && \
  "$1" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_MAJOR, $MIN_MINOR) else 1)" 2>/dev/null
}
REQUESTED="${PYTHON:-}"   # capture env override before we reassign PYTHON
PYTHON=""
if [ -n "$REQUESTED" ]; then
  is_ok "$REQUESTED" || die \
    "PYTHON=$REQUESTED is missing or older than ${MIN_MAJOR}.${MIN_MINOR}. Point it at a Python ${MIN_MAJOR}.${MIN_MINOR}+ interpreter."
  PYTHON="$REQUESTED"
else
  for cand in python3.13 python3.14 python3 python; do
    if is_ok "$cand"; then PYTHON="$cand"; break; fi
  done
fi
[ -n "$PYTHON" ] || die \
  "Python ${MIN_MAJOR}.${MIN_MINOR}+ not found. Install it (macOS: 'brew install python@3.13'), then rerun. Override with: PYTHON=/path/to/python ./run.sh"

"$PYTHON" -m venv --help >/dev/null 2>&1 || die \
  "The 'venv' module is missing for $PYTHON. On Debian/Ubuntu: sudo apt install python3-venv"

log "Using $($PYTHON -V 2>&1) ($PYTHON)"

# 1. Virtualenv ------------------------------------------------------------
# Rebuild the venv if it's missing or built with a different Python minor version.
TARGET_VER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ -d "$VENV" ]; then
  VENV_VER="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)"
  if [ "$VENV_VER" != "$TARGET_VER" ]; then
    log "Rebuilding venv (was Python $VENV_VER, want $TARGET_VER)..."
    rm -rf "$VENV"
  fi
fi
if [ ! -d "$VENV" ]; then
  log "Creating virtualenv ($VENV) with Python $TARGET_VER..."
  "$PYTHON" -m venv "$VENV"
else
  log "Virtualenv exists (Python $TARGET_VER) — reusing."
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 2. Dependencies ----------------------------------------------------------
# Reinstall only when requirements.txt changed since the last successful install.
STAMP="$VENV/.deps-installed"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  log "Installing dependencies..."
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements.txt
  touch "$STAMP"
else
  log "Dependencies up to date — skipping install."
fi

# 3. Environment file ------------------------------------------------------
if [ ! -f ".env" ]; then
  log "No .env found — creating one from .env.example (DEMO_MODE=true)."
  cp .env.example .env
else
  log ".env exists — leaving it untouched."
fi

# 4. Run (unless 'setup' was requested) ------------------------------------
if [ "${1:-run}" = "setup" ]; then
  log "Setup complete. Run './run.sh' to start the server."
  exit 0
fi

BASE="http://localhost:$PORT"
printf "\n\033[1;32m✈  Tailwind AI is starting — open the app:\033[0m\n"
printf "   \033[1;37mApp / UI      \033[0m %s\n"                    "$BASE"
printf "   \033[0;37mStatus (poll) \033[0m %s/status\n"            "$BASE"
printf "   \033[0;37mWebhook       \033[0m %s/vocalbridge/webhook\n" "$BASE"
printf "\n   \033[0;90m# after clicking the button, simulate the traveler saying \"yes\":\033[0m\n"
printf "   \033[0;37mcurl -X POST %s/vocalbridge/webhook -H 'Content-Type: application/json' \\\\\033[0m\n" "$BASE"
printf "   \033[0;37m     -d '{\"event\":\"transcript\",\"speaker\":\"user\",\"text\":\"yes book the next one\"}'\033[0m\n\n"

log "Server running on $BASE  (Ctrl+C to stop)"
exec uvicorn main:app --reload --port "$PORT"

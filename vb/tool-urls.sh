#!/usr/bin/env bash
# Print the 3 Vocal Bridge Custom API tool URLs for a given base URL, ready to
# paste into the VB dashboard. Makes switching between the Render deploy and the
# laptop tunnel a copy-paste, since the base changes but the paths don't.
#
#   vb/tool-urls.sh https://tailwind-ai.onrender.com     # deployed
#   vb/tool-urls.sh https://<something>.trycloudflare.com # laptop tunnel
#   vb/tool-urls.sh                                       # uses PUBLIC_BASE_URL from .env
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${1:-}"
if [ -z "$BASE" ] && [ -f .env ]; then
  BASE="$(grep -E '^PUBLIC_BASE_URL=' .env | tail -1 | cut -d= -f2-)"
fi
[ -n "$BASE" ] || { echo "usage: vb/tool-urls.sh <base-url>   (or set PUBLIC_BASE_URL in .env)"; exit 1; }
BASE="${BASE%/}"

printf "\nVocal Bridge → Custom API tools (paste each):\n\n"
printf "  %-30s %-5s %s\n" "get_cancellation_context"      "GET"  "$BASE/agent/context"
printf "  %-30s %-5s %s\n" "rebook_next_available_flight"  "POST" "$BASE/agent/rebook"
printf "  %-30s %-5s %s\n" "decline_rebooking"             "POST" "$BASE/agent/decline"
printf "\n"

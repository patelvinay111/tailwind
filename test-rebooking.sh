#!/usr/bin/env bash
# Exercise the rebooking flow against a running app (start it with ./run.sh first).
#   ./test-rebooking.sh                 # against http://localhost:8787
#   ./test-rebooking.sh https://xxx     # against a deployed/tunnel URL
set -euo pipefail
BASE="${1:-http://localhost:8787}"
j() { python3 -m json.tool 2>/dev/null || cat; }

echo "── 1) inform (get_cancellation_context) ──"
curl -s "$BASE/agent/context" | j

echo "── 2) set voice preferences: evening + max_budget 1000 ──"
curl -s -X POST "$BASE/preferences/update" -H 'Content-Type: application/json' \
  -d '{"category":"flight","field":"preferred_time","value":"evening"}' >/dev/null
curl -s -X POST "$BASE/preferences/update" -H 'Content-Type: application/json' \
  -d '{"category":"flight","field":"max_budget","value":1000}' >/dev/null
echo "   done."

echo "── 3) preference-aware search (real Sabre) ──"
curl -s -X POST "$BASE/agent/search-rebooking" -H 'Content-Type: application/json' -d '{}' | j

echo "── 4) live override on the call: nonstop ──"
curl -s -X POST "$BASE/agent/search-rebooking" -H 'Content-Type: application/json' -d '{"stops":"nonstop"}' | j

echo "── 5) book (handoff seam) ──"
curl -s -X POST "$BASE/agent/book" -H 'Content-Type: application/json' -d '{}' | j

echo "── 6) status ──"
curl -s "$BASE/agent/rebooking-status" | j

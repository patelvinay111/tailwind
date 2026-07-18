# ✈️ Tailwind AI

Proactive flight-disruption rebooking for the Voice AI Hackathon.

When a flight is cancelled, the agent **calls the traveler** (Vocal Bridge), offers to
rebook them, and on "yes" searches **Sabre** for real alternatives, picks the best one,
and books it. The web page shows the old vs. new itinerary.

**Requires Python 3.13** (pinned in `.python-version`).

## Run it (works offline out of the box)

```bash
./run.sh
```

That one command finds Python 3.13, creates the venv, installs deps, creates `.env`,
and starts the server — printing the URLs. Then open http://localhost:8787 and click
**Simulate Flight Cancellation**.

<details>
<summary>Manual steps (if you'd rather not use run.sh)</summary>

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # DEMO_MODE=true — no credentials needed to start
uvicorn main:app --reload --port 8787
```
</details>

In `DEMO_MODE`, no real call is placed. Simulate the traveler saying "yes" on the call:

```bash
curl -X POST http://localhost:8787/vocalbridge/webhook \
  -H 'Content-Type: application/json' \
  -d '{"event":"transcript","speaker":"user","text":"yes book the next one"}'
```

The page then fills in the rebooked flight.

## Going live (on-site)

- **Sabre** — set `SABRE_ACCESS_TOKEN` (Bearer) and `SABRE_LIVE=true` for real flight
  search. Booking stays simulated unless you deliberately set `SABRE_BOOKING_ENABLED=true`.
- **Vocal Bridge** — set `DEMO_MODE=false` + `VOCALBRIDGE_*` + `DEMO_USER_PHONE`. Run
  `ngrok http 8787` and set `PUBLIC_BASE_URL` so Vocal Bridge can reach `/vocalbridge/webhook`.
  Adjust request/webhook field names in `vocalbridge.py` (search for `TODO(on-site)`).

Each `TODO(on-site)` marks the exact spot to reconcile with the docs handed out at the event.

## Files

| File | Role |
|------|------|
| `main.py` | FastAPI app: routes, in-memory state, orchestration |
| `vocalbridge.py` | Outbound call trigger + webhook normalization |
| `sabre.py` | Flight search (Bargain Finder Max) + booking (Create PNR) |
| `agent.py` | Agent logic (rule-based): opening line, intent detection, flight selection |
| `static/index.html` | The single-page UI (vanilla JS, polls `/status`) |

## Flow

`POST /simulate-cancellation` → agent opener → Vocal Bridge call → traveler confirms →
`POST /vocalbridge/webhook` → Sabre search → pick best → Sabre book → `GET /status` shows both cards.

State machine: `idle → calling → awaiting_confirmation → rebooking → done` (or `declined` / `error`).

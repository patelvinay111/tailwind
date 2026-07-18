"""
Tailwind AI — FastAPI backend.

The demo loop:
  POST /simulate-cancellation  -> mark the hardcoded flight cancelled + start the call
  POST /vocalbridge/webhook    -> receive transcript; on "yes" -> search Sabre + rebook
  GET  /status                 -> frontend polls this for state + itineraries

Run it:
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  cp .env.example .env            # DEMO_MODE=true works out of the box
  uvicorn main:app --reload

Open http://localhost:8787  ->  click "Simulate Flight Cancellation".

Driving the demo OFFLINE (no real phone / Vocal Bridge):
  after clicking the button, simulate the traveler saying "yes":
    curl -X POST http://localhost:8787/vocalbridge/webhook \
      -H 'Content-Type: application/json' \
      -d '{"event":"transcript","speaker":"user","text":"yes book the next one"}'
"""
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

import agent
import sabre
import vocalbridge

app = FastAPI(title="Tailwind AI")

# Shared Sabre client (Bearer auth via SABRE_ACCESS_TOKEN in .env).
sabre_client = sabre.SabreClient()

# ---------------------------------------------------------------------------
# In-memory demo state (single run; no DB by design).
# state: idle -> calling -> awaiting_confirmation -> rebooking -> done | declined | error
# ---------------------------------------------------------------------------
STATE = {
    "state": "idle",
    "message": "Ready.",
    "old_itinerary": None,
    "new_itinerary": None,
    "call_id": None,
    "reason": None,
}
_lock = threading.Lock()

# The one hardcoded flight we "cancel". The rebooking SEARCH after this is real
# Sabre. Route/date chosen because Sabre CERT actually has inventory for JFK->LAX
# (InstaFlights 404s on routes with no CERT data, e.g. SFO->AUS).
HARDCODED_FLIGHT = {
    "flight_number": "B61234",
    "carrier": "JetBlue Airways",
    "origin": "JFK",
    "destination": "LAX",
    "depart": "2026-08-15T18:00:00",
    "arrive": "2026-08-15T21:20:00",
    "duration": "6h 20m",
    "stops": 0,
    "price": 329.00,
    "currency": "USD",
    "cabin": "Economy",
    "status": "CANCELLED",
    "confirmation": "JB-7K2P9Q",
}


def _set(**kwargs):
    with _lock:
        STATE.update(kwargs)


# ---------------------------------------------------------------------------
# 1. Kick off the whole flow
# ---------------------------------------------------------------------------
@app.post("/simulate-cancellation")
async def simulate_cancellation():
    old = dict(HARDCODED_FLIGHT)
    _set(
        state="calling",
        message="Flight cancelled. Calling you now…",
        old_itinerary=old,
        new_itinerary=None,
        reason=None,
    )

    opener = agent.opening_line(old)
    try:
        call = vocalbridge.trigger_call(
            to_number=os.getenv("DEMO_USER_PHONE", ""),
            opening_line=opener,
            context={"flight_number": old["flight_number"]},
        )
        _set(call_id=call.get("call_id"), state="awaiting_confirmation",
             message="On the call — waiting for you to confirm the rebooking.")
    except Exception as e:
        _set(state="error", message=f"Could not start the call: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    return {"ok": True, "opening_line": opener, "call": call, "state": STATE["state"]}


# ---------------------------------------------------------------------------
# 2. Vocal Bridge webhook — transcripts land here
# ---------------------------------------------------------------------------
@app.post("/vocalbridge/webhook")
async def vocalbridge_webhook(request: Request):
    payload = await request.json()
    event = vocalbridge.parse_webhook(payload)

    # Only act on what the traveler says.
    if event["type"] != "transcript" or (event["role"] and event["role"] == "agent"):
        return {"ok": True, "ignored": True, "event_type": event["type"]}

    interpretation = agent.interpret_response(event["text"])
    intent = interpretation["intent"]

    if intent == "confirm":
        # Run the (possibly slow) Sabre search+book off the request thread so the
        # webhook returns fast and the agent can keep talking.
        threading.Thread(target=_do_rebooking, daemon=True).start()
        return {"ok": True, "intent": intent, "reply": interpretation["reply"]}

    if intent == "decline":
        _set(state="declined", message="Traveler declined the rebooking.")
        return {"ok": True, "intent": intent, "reply": interpretation["reply"]}

    return {"ok": True, "intent": intent, "reply": interpretation["reply"]}


def _do_rebooking():
    """Search Sabre for alternatives, pick the best, then book. Updates STATE."""
    try:
        old = STATE["old_itinerary"]
        _set(state="rebooking", message="Finding the next available flight…")

        # Real Sabre search. If it errors or the route has no CERT inventory,
        # fall back to demo alternatives so the on-stage demo always completes.
        try:
            candidates = sabre.search_flights(old)
        except Exception as e:
            print(f"[main] Sabre search failed ({e}); using demo alternatives")
            candidates = []
        if not candidates:
            print("[main] no live alternatives; using demo alternatives")
            candidates = sabre._fake_search_results(
                old["origin"], old["destination"], old["depart"][:10]
            )

        choice = agent.pick_flight(old, candidates)
        chosen = choice["flight"]
        if not chosen:
            _set(state="error", message="No alternative flights available.")
            return

        _set(message=f"Rebooking {chosen['flight_number']} — {choice['reason']}")
        booking = sabre.book_flight(chosen)

        new_itin = dict(chosen)
        new_itin["status"] = booking["status"]
        new_itin["confirmation"] = booking["pnr"]
        _set(
            state="done",
            message=f"Done! Rebooked on {chosen['flight_number']}. Confirmation {booking['pnr']}.",
            new_itinerary=new_itin,
            reason=choice["reason"],
        )
    except Exception as e:
        _set(state="error", message=f"Rebooking failed: {e}")


# ---------------------------------------------------------------------------
# 3. Status (frontend polls this)
# ---------------------------------------------------------------------------
@app.get("/status")
async def status():
    with _lock:
        return dict(STATE)


@app.post("/reset")
async def reset():
    _set(state="idle", message="Ready.", old_itinerary=None, new_itinerary=None,
         call_id=None, reason=None)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 4. Sabre endpoints — hit each Sabre operation directly (for testing/debugging
#    independently of the voice flow). Handy on-site the moment your token lands.
# ---------------------------------------------------------------------------
class BookRequest(BaseModel):
    flight: dict                       # a normalized flight dict (as returned by /sabre/search)
    passenger: dict | None = None      # {"first_name": "...", "last_name": "..."}


@app.get("/sabre/health")
async def sabre_health():
    """Sanity check: is the client configured? Never returns the token itself."""
    return {
        "demo_mode": sabre._demo_mode(),
        "sabre_live_search": sabre._sabre_live(),
        "booking_enabled": sabre._booking_enabled(),   # false => bookings are simulated
        "base_url": sabre_client.base_url,
        "token_present": bool(sabre_client.access_token),
        "pcc": sabre_client.pcc or None,
    }


@app.get("/sabre/search")
async def sabre_search(
    origin: str = HARDCODED_FLIGHT["origin"],
    destination: str = HARDCODED_FLIGHT["destination"],
    date: str = HARDCODED_FLIGHT["depart"][:10],
    passengers: int = 1,
    limit: int = 5,
):
    """
    InstaFlights search. Browser-testable — defaults to the demo route, so
    GET /sabre/search just works, or override:
      /sabre/search?origin=JFK&destination=LAX&date=2026-07-18
    """
    try:
        flights = sabre_client.search_flights(origin, destination, date, passengers, limit)
        return {"ok": True, "count": len(flights), "flights": flights}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.post("/sabre/book")
async def sabre_book(req: BookRequest):
    """Create PNR for one flight. Body: {"flight": {...}, "passenger": {...}?}."""
    try:
        result = sabre_client.create_booking(req.flight, req.passenger)
        return {"ok": True, **result}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


# ---------------------------------------------------------------------------
# Static frontend (serve index.html at /). Mounted LAST so the API routes above
# take precedence over the catch-all static handler.
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")

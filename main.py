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

load_dotenv()

import agent
import sabre
import vocalbridge
from preferences import PreferenceStore

app = FastAPI(title="Tailwind AI")

# ---------------------------------------------------------------------------
# Preference engine (voice-based collection)
# ---------------------------------------------------------------------------
preference_store = PreferenceStore()

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

# The one hardcoded flight we "cancel". Everything after cancellation is real Sabre.
HARDCODED_FLIGHT = {
    "flight_number": "DL1420",
    "carrier": "Delta Air Lines",
    "origin": "SFO",
    "destination": "AUS",
    "depart": "2026-07-18T18:00:00",
    "arrive": "2026-07-18T23:45:00",
    "duration": "3h 45m",
    "stops": 0,
    "price": 232.00,
    "currency": "USD",
    "cabin": "Economy",
    "status": "CANCELLED",
    "confirmation": "Delta-JHQ4TZ",
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
    """Search Sabre for alternatives, let Claude pick, then book. Updates STATE."""
    try:
        old = STATE["old_itinerary"]
        _set(state="rebooking", message="Finding the next available flight…")

        candidates = sabre.search_flights(old)
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
# 4. Preference endpoints (voice-based collection)
# ---------------------------------------------------------------------------
@app.get("/preferences")
async def get_preferences():
    return preference_store.get_all()


@app.post("/preferences/update")
async def update_preference(request: Request):
    body = await request.json()
    category = body.get("category")
    field = body.get("field")
    value = body.get("value")
    if not category or not field:
        return JSONResponse({"ok": False, "error": "category and field required"}, status_code=400)
    return preference_store.update(category, field, value)


@app.post("/preferences/confirm")
async def confirm_preferences():
    return preference_store.confirm()


@app.post("/preferences/ready")
async def mark_ready():
    return preference_store.mark_ready()


@app.post("/preferences/invalidate")
async def invalidate_preferences(request: Request):
    body = await request.json()
    return preference_store.invalidate(body.get("reason", ""))


@app.post("/preferences/reset")
async def reset_preferences():
    return preference_store.reset()


# ---------------------------------------------------------------------------
# 5. Voice token proxy (keeps API key server-side)
# ---------------------------------------------------------------------------
@app.post("/api/voice-token")
async def voice_token(request: Request):
    vb_api_key = os.getenv("VOCALBRIDGE_API_KEY", "")
    vb_agent_id = os.getenv("VOCALBRIDGE_AGENT_ID", "")
    if not vb_api_key:
        return JSONResponse({"error": "VOCALBRIDGE_API_KEY not set"}, status_code=500)

    import httpx
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    headers = {
        "X-API-Key": vb_api_key,
        "Content-Type": "application/json",
    }
    if vb_agent_id:
        headers["X-Agent-Id"] = vb_agent_id

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://vocalbridgeai.com/api/v1/token",
            headers=headers,
            json={"participant_name": body.get("participant_name", "Traveler")},
            timeout=15,
        )
    if resp.status_code != 200:
        return JSONResponse({"error": "Token fetch failed", "detail": resp.text}, status_code=resp.status_code)
    return resp.json()


# ---------------------------------------------------------------------------
# Static frontend (serve index.html at /)
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")

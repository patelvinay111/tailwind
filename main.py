"""
Tailwind AI — FastAPI backend.

Architecture:
  VOICE PATH: Vocal Bridge is the brain. It handles STT → AI thinking → tool calls → TTS.
    - VB calls our HTTP API tool endpoints when it needs travel data
    - Our backend is a "headless travel API" that VB's AI orchestrates

  TEXT PATH: Falls back to Claude for users who type instead of speak.

  DISRUPTION PATH: Proactive outbound call flow (original demo).

API Tool Endpoints (registered as VB Custom HTTP Tools):
  POST /api/flights/search    -> search flights via Sabre
  POST /api/hotels/search     -> search hotels via Sabre
  POST /api/hotels/rates      -> get hotel rates
  POST /api/price/check       -> verify price before booking
  POST /api/book              -> book the trip
  POST /api/preferences       -> get traveler preferences

Session/UI Endpoints (frontend polls these):
  POST /api/voice-token       -> Vocal Bridge WebRTC token proxy
  POST /conversation          -> text-mode fallback (Claude)
  POST /select-option         -> card click → text conversation
  GET  /status                -> full session state
  POST /reset                 -> start fresh

Disruption Endpoints:
  POST /simulate-cancellation -> outbound call flow
  POST /vocalbridge/webhook   -> transcript events

Run:
  uvicorn main:app --reload --port 8787
"""
import os
import threading
import time

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

sabre_client = sabre.SabreClient()


# ---------------------------------------------------------------------------
# Session state — single user, in-memory (hackathon scope)
# ---------------------------------------------------------------------------
SESSION = {
    "messages": [],
    "transcript": [],
    "display": {
        "flight_options": [],
        "hotel_options": [],
        "itinerary": [],
        "summary": None,
        "booking_confirmed": None,
    },
    "mode": "booking",
    "state": "idle",
    "old_itinerary": None,
    "new_itinerary": None,
    "call_id": None,
    "reason": None,
}
_lock = threading.Lock()


def _update(**kwargs):
    with _lock:
        SESSION.update(kwargs)


def _reset_session():
    with _lock:
        SESSION.update({
            "messages": [],
            "transcript": [],
            "display": {
                "flight_options": [],
                "hotel_options": [],
                "itinerary": [],
                "summary": None,
                "booking_confirmed": None,
            },
            "mode": "booking",
            "state": "idle",
            "old_itinerary": None,
            "new_itinerary": None,
            "call_id": None,
            "reason": None,
        })


# ===========================================================================
# VB TOOL ENDPOINTS — These are registered as Custom HTTP Tools in Vocal Bridge.
# VB's AI brain calls these when it decides to search/book/etc.
# ===========================================================================

class FlightSearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: str
    return_date: str | None = None
    cabin: str = "Economy"
    max_results: int = 5


@app.post("/api/flights/search")
async def api_flights_search(req: FlightSearchRequest):
    """
    VB Tool: Search flights. VB's AI calls this when user asks about flights.
    Returns flight options that VB will read aloud + we push to the UI.
    """
    flights = sabre.search_flights_v2(
        origin=req.origin,
        destination=req.destination,
        departure_date=req.departure_date,
        return_date=req.return_date,
        cabin=req.cabin,
        max_results=req.max_results,
    )

    # Update UI state so frontend shows cards
    with _lock:
        SESSION["display"]["flight_options"] = flights
        SESSION["state"] = "connected"

    # Return structured data for VB to speak
    prefs = agent.load_preferences()
    preferred = prefs.get("flight_preferences", {}).get("preferred_airlines", [])
    return {
        "flights": flights,
        "count": len(flights),
        "preferred_airlines": preferred,
        "note": f"Traveler prefers {', '.join(preferred)}. Prioritize nonstop flights.",
    }


class HotelSearchRequest(BaseModel):
    location: str
    check_in: str
    check_out: str
    guests: int = 1
    max_price_per_night: float | None = None


@app.post("/api/hotels/search")
async def api_hotels_search(req: HotelSearchRequest):
    """VB Tool: Search hotels near a location."""
    prefs = agent.load_preferences()
    max_price = req.max_price_per_night or prefs.get("hotel_preferences", {}).get("budget_per_night_usd")

    hotels = sabre.search_hotels(
        location=req.location,
        check_in=req.check_in,
        check_out=req.check_out,
        guests=req.guests,
        max_price=max_price,
    )

    with _lock:
        SESSION["display"]["hotel_options"] = hotels
        SESSION["state"] = "connected"

    preferred = prefs.get("hotel_preferences", {}).get("preferred_chains", [])
    return {
        "hotels": hotels,
        "count": len(hotels),
        "preferred_chains": preferred,
        "note": f"Traveler prefers {', '.join(preferred)}. Budget ${max_price}/night.",
    }


class HotelRatesRequest(BaseModel):
    hotel_code: str
    check_in: str
    check_out: str
    guests: int = 1


@app.post("/api/hotels/rates")
async def api_hotels_rates(req: HotelRatesRequest):
    """VB Tool: Get detailed rates for a specific hotel."""
    rates = sabre.get_hotel_rates(
        hotel_code=req.hotel_code,
        check_in=req.check_in,
        check_out=req.check_out,
        guests=req.guests,
    )
    return {"rates": rates, "hotel_code": req.hotel_code}


class PriceCheckRequest(BaseModel):
    item_type: str  # "flight" | "hotel"
    offer_id: str


@app.post("/api/price/check")
async def api_price_check(req: PriceCheckRequest):
    """VB Tool: Verify price before booking."""
    result = sabre.check_price(item_type=req.item_type, offer_id=req.offer_id)
    return result


class BookRequest(BaseModel):
    flights: list[dict] = []
    hotel: dict | None = None
    traveler_name: str | None = None


@app.post("/api/book")
async def api_book(req: BookRequest):
    """VB Tool: Book the trip (flights + optional hotel)."""
    prefs = agent.load_preferences()
    name = req.traveler_name or prefs.get("traveler", {}).get("name", "DEMO TRAVELER")
    loyalty = prefs.get("flight_preferences", {}).get("loyalty_programs", [])

    result = sabre.book_trip(
        flights=req.flights,
        hotel=req.hotel,
        traveler_name=name,
        loyalty=loyalty,
    )

    # Update UI
    with _lock:
        SESSION["display"]["booking_confirmed"] = result
        SESSION["state"] = "done"

    return result


@app.get("/api/preferences")
async def api_preferences():
    """VB Tool: Get traveler preferences so VB's AI can personalize responses."""
    prefs = agent.load_preferences()
    return prefs


# ===========================================================================
# VOICE TOKEN — Frontend gets this to connect to VB WebRTC
# ===========================================================================

@app.post("/api/voice-token")
async def voice_token():
    """Proxy for Vocal Bridge WebRTC token."""
    try:
        token_data = vocalbridge.get_webrtc_token()
        return token_data
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


# ===========================================================================
# UI UPDATE — VB's agent actions come here (or we push from tool calls)
# ===========================================================================

@app.post("/api/ui/update")
async def ui_update(request: Request):
    """
    VB can call this tool to explicitly update the user's screen.
    Actions: show_flight_options, show_hotel_options, add_to_itinerary,
             show_summary, booking_confirmed, clear_options
    """
    payload = await request.json()
    action = payload.get("action")
    data = payload.get("data", {})

    with _lock:
        if action == "show_flight_options":
            SESSION["display"]["flight_options"] = data.get("flights", [])
        elif action == "show_hotel_options":
            SESSION["display"]["hotel_options"] = data.get("hotels", [])
        elif action == "add_to_itinerary":
            SESSION["display"]["itinerary"].append(data)
        elif action == "show_summary":
            SESSION["display"]["summary"] = data
        elif action == "booking_confirmed":
            SESSION["display"]["booking_confirmed"] = data
            SESSION["state"] = "done"
        elif action == "clear_options":
            SESSION["display"]["flight_options"] = []
            SESSION["display"]["hotel_options"] = []

    return {"ok": True}


# ===========================================================================
# TEXT FALLBACK — For users typing (Claude handles this path)
# ===========================================================================

class ConversationRequest(BaseModel):
    text: str
    source: str = "web"


@app.post("/conversation")
async def conversation(req: ConversationRequest):
    """Text-mode conversation. Uses Claude tool-use as the brain."""
    user_text = req.text.strip()
    if not user_text:
        return JSONResponse({"ok": False, "error": "Empty message"}, status_code=400)

    with _lock:
        SESSION["transcript"].append({"role": "user", "text": user_text, "ts": time.time()})
        SESSION["state"] = "searching"

    preferences = agent.load_preferences()
    result = agent.run_conversation_turn(
        messages=SESSION["messages"],
        user_text=user_text,
        preferences=preferences,
    )

    with _lock:
        SESSION["messages"] = result["messages"]
        SESSION["transcript"].append({"role": "agent", "text": result["reply"], "ts": time.time()})

        for update in result.get("display_updates", []):
            _apply_display_update(update)

        if result.get("booking"):
            SESSION["state"] = "done"
            SESSION["display"]["booking_confirmed"] = result["booking"]
        else:
            SESSION["state"] = "connected"

    return {
        "ok": True,
        "reply": result["reply"],
        "display_updates": result.get("display_updates", []),
        "booking": result.get("booking"),
        "state": SESSION["state"],
    }


def _apply_display_update(update: dict):
    action = update.get("action")
    data = update.get("data", {})
    if action == "show_flight_options":
        SESSION["display"]["flight_options"] = data.get("flights", [])
    elif action == "show_hotel_options":
        SESSION["display"]["hotel_options"] = data.get("hotels", [])
    elif action == "add_to_itinerary":
        SESSION["display"]["itinerary"].append(data.get("item", data))
    elif action == "show_summary":
        SESSION["display"]["summary"] = data
    elif action == "clear_options":
        SESSION["display"]["flight_options"] = []
        SESSION["display"]["hotel_options"] = []
    elif action == "booking_confirmed":
        SESSION["display"]["booking_confirmed"] = data


class SelectOptionRequest(BaseModel):
    option_type: str
    index: int
    label: str | None = None


@app.post("/select-option")
async def select_option(req: SelectOptionRequest):
    """Card click → conversation turn."""
    with _lock:
        options = (SESSION["display"]["flight_options"] if req.option_type == "flight"
                   else SESSION["display"]["hotel_options"])

    if req.index < 0 or req.index >= len(options):
        return JSONResponse({"ok": False, "error": "Invalid option index"}, status_code=400)

    selected = options[req.index]
    if req.label:
        text = req.label
    elif req.option_type == "flight":
        text = f"I'll take the {selected.get('carrier', '')} {selected.get('flight_number', '')} flight"
    else:
        text = f"I'll take the {selected.get('name', 'that hotel')}"

    conv_req = ConversationRequest(text=text, source="click")
    return await conversation(conv_req)


# ===========================================================================
# STATUS + RESET
# ===========================================================================

@app.get("/status")
async def status():
    with _lock:
        return {
            "mode": SESSION["mode"],
            "state": SESSION["state"],
            "transcript": SESSION["transcript"][-50:],
            "display": SESSION["display"],
            "old_itinerary": SESSION["old_itinerary"],
            "new_itinerary": SESSION["new_itinerary"],
            "reason": SESSION["reason"],
            "message": _status_message(),
        }


def _status_message() -> str:
    s = SESSION["state"]
    messages = {
        "idle": "Ready. Click Start Planning or simulate a disruption.",
        "connected": "Listening...",
        "searching": "Searching...",
        "booking": "Booking your trip...",
        "done": "Trip booked! 🎉",
        "calling": "Calling you now...",
        "awaiting_confirmation": "On the call — waiting for confirmation.",
        "rebooking": "Finding the next available flight...",
        "declined": "Traveler declined.",
        "error": "Something went wrong.",
    }
    return messages.get(s, "")


@app.post("/reset")
async def reset():
    _reset_session()
    return {"ok": True}


# ===========================================================================
# DISRUPTION MODE — outbound call flow
# ===========================================================================

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


@app.post("/simulate-cancellation")
async def simulate_cancellation():
    old = dict(HARDCODED_FLIGHT)
    _update(mode="disruption", state="calling", old_itinerary=old, new_itinerary=None, reason=None)

    opener = agent.opening_line(old)
    try:
        call = vocalbridge.trigger_call(
            to_number=os.getenv("DEMO_USER_PHONE", ""),
            opening_line=opener,
            context={"flight_number": old["flight_number"]},
        )
        _update(call_id=call.get("call_id"), state="awaiting_confirmation")
    except Exception as e:
        _update(state="error")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    return {"ok": True, "opening_line": opener, "call": call, "state": SESSION["state"]}


@app.post("/vocalbridge/webhook")
async def vocalbridge_webhook(request: Request):
    payload = await request.json()
    event = vocalbridge.parse_webhook(payload)

    if event["type"] != "transcript" or (event["role"] and event["role"] == "agent"):
        return {"ok": True, "ignored": True, "event_type": event["type"]}

    # In booking mode, VB is the brain — webhooks are just for transcript display
    if SESSION["mode"] == "booking":
        with _lock:
            SESSION["transcript"].append({"role": event["role"] or "user", "text": event["text"], "ts": time.time()})
        return {"ok": True}

    # Disruption mode
    interpretation = agent.interpret_response(event["text"])
    intent = interpretation["intent"]

    if intent == "confirm":
        threading.Thread(target=_do_rebooking, daemon=True).start()
        return {"ok": True, "intent": intent, "reply": interpretation["reply"]}
    if intent == "decline":
        _update(state="declined")
        return {"ok": True, "intent": intent, "reply": interpretation["reply"]}
    return {"ok": True, "intent": intent, "reply": interpretation["reply"]}


def _do_rebooking():
    try:
        old = SESSION["old_itinerary"]
        _update(state="rebooking")

        try:
            candidates = sabre.search_flights(old)
        except Exception:
            candidates = []
        if not candidates:
            candidates = sabre._fake_search_results(old["origin"], old["destination"], old["depart"][:10])

        choice = agent.pick_flight(old, candidates)
        chosen = choice["flight"]
        if not chosen:
            _update(state="error")
            return

        booking = sabre.book_flight(chosen)
        new_itin = dict(chosen)
        new_itin["status"] = booking["status"]
        new_itin["confirmation"] = booking["pnr"]
        _update(state="done", new_itinerary=new_itin, reason=choice["reason"])
    except Exception:
        _update(state="error")


# ===========================================================================
# SABRE DEBUG (direct testing)
# ===========================================================================

@app.get("/sabre/health")
async def sabre_health():
    return {
        "demo_mode": sabre._demo_mode(),
        "sabre_live_search": sabre._sabre_live(),
        "booking_enabled": sabre._booking_enabled(),
        "base_url": sabre_client.base_url,
        "token_present": bool(sabre_client.access_token),
        "pcc": sabre_client.pcc or None,
    }


# ===========================================================================
# Static frontend — mounted LAST
# ===========================================================================
app.mount("/", StaticFiles(directory="static", html=True), name="static")

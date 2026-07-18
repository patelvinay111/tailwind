"""
Rebooking flow (our scope) — works on a full ITINERARY.

Flow:
  1. cancellation-trigger : mark the itinerary's flight CANCELLED in OUR records
     (data/itinerary.json), sanity-check the status, then place the outbound call.
  2. context              : give the agent the COMPLETE itinerary (passenger, all
     flights + statuses, which one was cancelled) so it has full context.
  3. search-rebooking     : real Sabre search for the cancelled leg, ranked by the
     traveler's voice-collected preferences (+ live overrides).
  4. book                 : replace the cancelled leg with the chosen flight, mark
     the itinerary 'rebooked' (HANDOFF seam to the team's real Create PNR).

Data files (all JSON, git-checkinable):
  config.json                 tunables (budget, options, time windows)
  data/itinerary.sample.json  pristine SAMPLE itinerary (for testing / reset)
  data/itinerary.json         the LIVE itinerary (updated as the flow runs)

Self-contained APIRouter; main.py just does:
    import rebooking
    rebooking.set_store(preference_store)
    app.include_router(rebooking.router)
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import threading
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

import sabre
import vocalbridge

router = APIRouter()
_lock = threading.Lock()

_HERE = pathlib.Path(__file__).resolve().parent
DATA_DIR = _HERE / "data"
SAMPLE_FILE = DATA_DIR / "itinerary.sample.json"
ITINERARY_FILE = DATA_DIR / "itinerary.json"

# ---------------------------------------------------------------------------
# Config (tunables) — config.json
# ---------------------------------------------------------------------------
_CONFIG_DEFAULTS = {
    "default_max_budget_usd": 1000,
    "max_options": 3,
    "time_windows": {
        "early_morning": [4, 8], "morning": [8, 12], "afternoon": [12, 17],
        "evening": [17, 21], "red_eye": [21, 28],
    },
}


def _load_json(path: pathlib.Path, fallback: dict) -> dict:
    try:
        loaded = json.loads(path.read_text())
        return {k: v for k, v in loaded.items() if not k.startswith("_")}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[rebooking] {path.name} not loaded ({e}); using defaults")
        return dict(fallback)


_CFG = {**_CONFIG_DEFAULTS, **_load_json(_HERE / "config.json", _CONFIG_DEFAULTS)}
DEFAULT_MAX_BUDGET = _CFG["default_max_budget_usd"]
MAX_OPTIONS = _CFG["max_options"]
_TIME_WINDOWS = {k: tuple(v) for k, v in _CFG["time_windows"].items()}

# ---------------------------------------------------------------------------
# Itinerary state — loaded from data/itinerary.json, seeded from the sample.
# ---------------------------------------------------------------------------
_SAMPLE_FALLBACK = {
    "itinerary_id": "TW-DEMO-001",
    "passenger": {"name": "Sam Traveler", "phone": "+19255686514"},
    "confirmation": "JB-7K2P9Q",
    "status": "confirmed",
    "flights": [{
        "flight_number": "B61234", "carrier": "JetBlue Airways",
        "origin": "JFK", "destination": "LAX",
        "depart": "2026-08-15T18:00:00", "arrive": "2026-08-15T21:20:00",
        "stops": 0, "price": 329.00, "currency": "USD", "cabin": "Economy",
        "status": "CONFIRMED",
    }],
    "rebooking": {"options": [], "selected": None},
    "updated_at": None,
}


def _sample() -> dict:
    return _load_json(SAMPLE_FILE, _SAMPLE_FALLBACK)


_itin: dict = {}


def _save_locked() -> None:
    """Persist the live itinerary. Caller holds _lock."""
    try:
        DATA_DIR.mkdir(exist_ok=True)
        _itin["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        ITINERARY_FILE.write_text(json.dumps(_itin, indent=2))
    except OSError as e:
        print(f"[rebooking] could not save itinerary: {e}")


def _load_or_seed() -> None:
    """Load the live itinerary, or seed it from the sample on first run."""
    global _itin
    try:
        _itin = json.loads(ITINERARY_FILE.read_text())
        if "flights" not in _itin:               # old/flat file → reseed
            raise ValueError("stale shape")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        _itin = _sample()
        with _lock:
            _save_locked()


_load_or_seed()


def _cancelled_flight() -> Optional[dict]:
    """The CANCELLED leg (or the first flight if none is marked yet)."""
    flights = _itin.get("flights") or []
    return next((f for f in flights if f.get("status") == "CANCELLED"), flights[0] if flights else None)


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------
_store = None


def set_store(store) -> None:
    global _store
    _store = store


def _flight_prefs() -> dict:
    if _store is None:
        return {}
    prefs = (_store.get_all() or {}).get("preferences", {}).get("flight", {}) or {}
    return {k: v for k, v in prefs.items() if v not in (None, "", [])}


def _depart_hour(f: dict) -> int:
    try:
        return int(f["depart"].split("T")[1][:2])
    except (KeyError, IndexError, ValueError):
        return -1


def _in_window(hour: int, key: str) -> bool:
    if key not in _TIME_WINDOWS or hour < 0:
        return False
    lo, hi = _TIME_WINDOWS[key]
    h = hour + 24 if (key == "red_eye" and hour < 4) else hour
    return lo <= h < hi


def _apply_preferences(candidates: list[dict], prefs: dict) -> tuple[list[dict], bool]:
    stops_pref = prefs.get("stops")
    budget = prefs.get("max_budget")
    airline = (prefs.get("airline_preference") or "").lower()
    time_pref = prefs.get("preferred_time")

    def hard_ok(f: dict) -> bool:
        if stops_pref == "nonstop" and f.get("stops", 9) != 0:
            return False
        if stops_pref == "1_stop" and f.get("stops", 9) > 1:
            return False
        if budget and f.get("price", 1e9) > float(budget):
            return False
        return True

    filtered = [f for f in candidates if hard_ok(f)]
    relaxed = not filtered and bool(candidates)
    pool = filtered or list(candidates)

    def score(f: dict):
        s = 0
        if airline and (airline in f.get("carrier", "").lower()
                        or airline in f.get("carrier_code", "").lower()):
            s -= 100
        if time_pref and _in_window(_depart_hour(f), time_pref):
            s -= 50
        return (s, f.get("arrive", ""), f.get("stops", 9), f.get("price", 1e9))

    return sorted(pool, key=score), relaxed


def _friendly_time(iso: str) -> str:
    try:
        hh = int(iso.split("T")[1][:2]); mm = iso.split("T")[1][3:5]
        ampm = "AM" if hh < 12 else "PM"; h12 = hh % 12 or 12
        return f"{h12}:{mm} {ampm}"
    except (IndexError, ValueError):
        return "soon"


def _spoken_options(options: list[dict], relaxed: bool) -> str:
    top = options[0]
    when = _friendly_time(top.get("depart", ""))
    stops = "nonstop" if top.get("stops") == 0 else f"{top.get('stops')} stop"
    line = (f"The best match is {top['carrier']} flight {top['flight_number']}, "
            f"departing {when}, {stops}, ${top.get('price', 0):.0f}.")
    if relaxed:
        line += " I couldn't match all your preferences exactly, so this is the closest option."
    line += " I have a couple of other options too. Want me to book this one?" if len(options) > 1 else " Want me to book it?"
    return line


# ---------------------------------------------------------------------------
# Endpoints (VB Custom HTTP Tools)
# ---------------------------------------------------------------------------
class TriggerReq(BaseModel):
    phone_number: Optional[str] = None


@router.post("/agent/cancellation-trigger")
async def cancellation_trigger(req: TriggerReq):
    """On a cancellation: FIRST get the trip on record, then mark it disrupted,
    verify, and only then place the outbound call to that traveler."""
    # 1. Get the trip details first — nothing to do if there's no trip on record.
    with _lock:
        trip = json.loads(json.dumps(_itin))
    if not trip.get("flights"):
        return {"ok": False, "error": "No trip on record to act on."}

    # 2. Record the disruption (flight -> CANCELLED, itinerary -> disrupted).
    with _lock:
        for fl in _itin.get("flights", []):
            fl["status"] = "CANCELLED"
        _itin["status"] = "disrupted"
        _itin["rebooking"] = {"options": [], "selected": None}
        _save_locked()
        trip = json.loads(json.dumps(_itin))
    cancelled = next((f for f in trip["flights"] if f.get("status") == "CANCELLED"), None)
    phone = (trip.get("passenger") or {}).get("phone")

    # 3. Sanity-check OUR records before dialing.
    if trip["status"] != "disrupted" or not cancelled:
        return {"ok": False, "error": "Itinerary is not in a cancelled state; not calling."}

    # 4. Call the traveler, using the number from the trip.
    to = req.phone_number or phone or os.getenv("DEMO_USER_PHONE", "")
    call = vocalbridge.trigger_call(to_number=to, context={"itinerary_id": trip.get("itinerary_id")})
    return {"ok": True, "call": call, "trip": trip, "cancelled_flight": cancelled}


@router.get("/agent/context")
async def context():
    """Tool: get_cancellation_context — the COMPLETE itinerary + what was cancelled."""
    with _lock:
        itin = json.loads(json.dumps(_itin))   # deep copy
    cancelled = next((f for f in itin.get("flights", []) if f.get("status") == "CANCELLED"), None)
    pax = (itin.get("passenger") or {}).get("name", "the traveler")
    if cancelled:
        spoken = (f"{pax}, your {cancelled['carrier']} flight {cancelled['flight_number']} from "
                  f"{cancelled['origin']} to {cancelled['destination']} was cancelled.")
    else:
        spoken = f"{pax}, your itinerary is confirmed — no cancellations."
    return {
        "itinerary_id": itin.get("itinerary_id"),
        "passenger": itin.get("passenger"),
        "itinerary_status": itin.get("status"),
        "flights": itin.get("flights"),
        "cancelled_flight": cancelled,
        "spoken": spoken,
    }


class SearchReq(BaseModel):
    airline_preference: Optional[str] = None
    stops: Optional[str] = None
    preferred_time: Optional[str] = None
    cabin_class: Optional[str] = None
    max_budget: Optional[float] = None


@router.post("/agent/search-rebooking")
async def search_rebooking(req: SearchReq):
    """Tool: search_rebooking_options — real Sabre search for the cancelled leg."""
    cancelled = _cancelled_flight()
    if not cancelled:
        return {"ok": False, "options": [], "spoken": "There's no cancelled flight to rebook."}

    overrides = req.model_dump(exclude_none=True)
    prefs = {"max_budget": DEFAULT_MAX_BUDGET, **_flight_prefs(), **overrides}

    try:
        candidates = sabre.search_flights(cancelled)
    except Exception as e:
        print(f"[rebooking] Sabre search failed: {e}")
        candidates = []

    ranked, relaxed = _apply_preferences(candidates, prefs) if candidates else ([], False)
    options = ranked[:MAX_OPTIONS]
    with _lock:
        _itin.setdefault("rebooking", {})["options"] = options
        _save_locked()

    if not options:
        return {"ok": False, "options": [],
                "spoken": "I'm sorry, I couldn't find any alternative flights on that route right now."}
    return {"ok": True, "options": options, "applied_preferences": prefs,
            "spoken": _spoken_options(options, relaxed)}


class BookReq(BaseModel):
    flight_number: Optional[str] = None


@router.post("/agent/book")
async def book(req: BookReq):
    """Tool: book_selected_flight. HANDOFF seam to the team's real Create PNR."""
    with _lock:
        opts = (_itin.get("rebooking") or {}).get("options") or []
    chosen = next((o for o in opts if o.get("flight_number") == req.flight_number), None) or (opts[0] if opts else None)
    if not chosen:
        return {"ok": False, "spoken": "I don't have a flight selected to book yet — let me search first."}

    # --- TODO(team): replace with the real Sabre Create PNR booking call ---
    booking = sabre.book_flight(chosen)
    # -----------------------------------------------------------------------

    new_seg = dict(chosen); new_seg["status"] = "CONFIRMED"
    with _lock:
        _itin["flights"] = [new_seg if f.get("status") == "CANCELLED" else f
                            for f in _itin.get("flights", [])]
        _itin["status"] = "rebooked"
        _itin["confirmation"] = booking["pnr"]
        _itin.setdefault("rebooking", {})["selected"] = chosen
        _save_locked()

    return {
        "ok": True, "confirmation": booking["pnr"], "flight": new_seg,
        "spoken": (f"You're all set — rebooked on {chosen['carrier']} flight "
                   f"{chosen['flight_number']}, confirmation {booking['pnr']}."),
    }


@router.get("/agent/rebooking-status")
async def rebooking_status():
    """Full live itinerary — for the web UI to poll."""
    with _lock:
        return json.loads(json.dumps(_itin))


@router.post("/agent/rebooking-reset")
async def rebooking_reset():
    """Restore the pristine SAMPLE itinerary (confirmed, not cancelled)."""
    global _itin
    with _lock:
        _itin = _sample()
        _save_locked()
    return {"ok": True, "status": _itin.get("status")}

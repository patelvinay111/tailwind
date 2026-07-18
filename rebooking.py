"""
Rebooking flow (our scope) — cancellation trigger → outbound call → inform →
PREFERENCE-AWARE Sabre search → present options → hand off to booking (team).

Self-contained FastAPI APIRouter so it doesn't collide with the churning main.py.
main.py only needs three lines:

    import rebooking
    rebooking.set_store(preference_store)     # share the voice-collected prefs
    app.include_router(rebooking.router)

The VB agent (Custom HTTP Tools) calls:
    GET  /agent/context           -> get_cancellation_context (inform)
    POST /agent/search-rebooking  -> search_rebooking_options (honors preferences)
    POST /agent/book              -> book_selected_flight (HANDOFF to team's Create PNR)
    POST /agent/cancellation-trigger -> place the outbound call (system-triggered)
    GET  /agent/rebooking-status  -> UI polling
"""
from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Config — tunables in config.json; the cancellation SCENARIO in scenario.json.
# Both are data files (not hardcoded); edit those, not this module.
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).resolve().parent

_CONFIG_DEFAULTS = {
    "default_max_budget_usd": 1000,
    "max_options": 3,
    "time_windows": {
        "early_morning": [4, 8], "morning": [8, 12], "afternoon": [12, 17],
        "evening": [17, 21], "red_eye": [21, 28],
    },
}

_SCENARIO_DEFAULT = {
    "flight_number": "B61234", "carrier": "JetBlue Airways",
    "origin": "JFK", "destination": "LAX",
    "depart": "2026-08-15T18:00:00", "arrive": "2026-08-15T21:20:00",
    "stops": 0, "price": 329.00, "currency": "USD", "cabin": "Economy",
    "status": "CANCELLED", "confirmation": "JB-7K2P9Q",
}


def _load_json(filename: str, fallback: dict) -> dict:
    try:
        loaded = json.loads((_HERE / filename).read_text())
        return {k: v for k, v in loaded.items() if not k.startswith("_")}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[rebooking] {filename} not loaded ({e}); using defaults")
        return dict(fallback)


_CFG = {**_CONFIG_DEFAULTS, **_load_json("config.json", _CONFIG_DEFAULTS)}
DEFAULT_MAX_BUDGET = _CFG["default_max_budget_usd"]
MAX_OPTIONS = _CFG["max_options"]

_SCENARIO = _load_json("scenario.json", {"cancelled_flight": _SCENARIO_DEFAULT})

# ---------------------------------------------------------------------------
# Shared PreferenceStore (injected from main.py so we read the SAME prefs the
# voice-collection endpoints write). Optional — falls back to no prefs.
# ---------------------------------------------------------------------------
_store = None


def set_store(store) -> None:
    global _store
    _store = store


# Staged cancelled flight (from scenario.json; the trigger can override it).
DEFAULT_CANCELLED_FLIGHT = _SCENARIO["cancelled_flight"]

_state = {"cancelled_flight": None, "options": [], "selected": None, "status": "idle"}


def _set(**kw):
    with _lock:
        _state.update(kw)


# ---------------------------------------------------------------------------
# Preference handling
# ---------------------------------------------------------------------------
def _flight_prefs() -> dict:
    """Voice-collected flight preferences (non-empty only)."""
    if _store is None:
        return {}
    prefs = (_store.get_all() or {}).get("preferences", {}).get("flight", {}) or {}
    return {k: v for k, v in prefs.items() if v not in (None, "", [])}


# local departure-hour ranges (from config.json); red_eye wraps past midnight
_TIME_WINDOWS = {k: tuple(v) for k, v in _CFG["time_windows"].items()}


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
    """
    HARD-filter by stops/budget, then rank by airline + preferred-time match,
    then soonest arrival / fewest stops / price. Returns (ranked, relaxed) where
    `relaxed` means the hard filters removed everything so we fell back to all.
    """
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


def _spoken_options(options: list[dict], prefs: dict, relaxed: bool) -> str:
    top = options[0]
    when = _friendly_time(top.get("depart", ""))
    stops = "nonstop" if top.get("stops") == 0 else f"{top.get('stops')} stop"
    line = (f"The best match is {top['carrier']} flight {top['flight_number']}, "
            f"departing {when}, {stops}, ${top.get('price', 0):.0f}.")
    if relaxed:
        line += " I couldn't match all your preferences exactly, so this is the closest option."
    if len(options) > 1:
        line += " I have a couple of other options too. Want me to book this one?"
    else:
        line += " Want me to book it?"
    return line


def _friendly_time(iso: str) -> str:
    try:
        hh = int(iso.split("T")[1][:2]); mm = iso.split("T")[1][3:5]
        ampm = "AM" if hh < 12 else "PM"; h12 = hh % 12 or 12
        return f"{h12}:{mm} {ampm}"
    except (IndexError, ValueError):
        return "soon"


# ---------------------------------------------------------------------------
# Endpoints (VB Custom HTTP Tools)
# ---------------------------------------------------------------------------
class TriggerReq(BaseModel):
    phone_number: Optional[str] = None
    flight: Optional[dict] = None


@router.post("/agent/cancellation-trigger")
async def cancellation_trigger(req: TriggerReq):
    """Stage the cancellation and place the outbound call to the traveler."""
    flight = req.flight or dict(DEFAULT_CANCELLED_FLIGHT)
    _set(cancelled_flight=flight, options=[], selected=None, status="calling")
    to = req.phone_number or os.getenv("DEMO_USER_PHONE", "")
    call = vocalbridge.trigger_call(to_number=to, context={"flight_number": flight["flight_number"]})
    _set(status="on_call")
    return {"ok": True, "call": call, "cancelled_flight": flight}


@router.get("/agent/context")
async def context():
    """Tool: get_cancellation_context — what was cancelled, so the agent can inform."""
    f = _state["cancelled_flight"] or dict(DEFAULT_CANCELLED_FLIGHT)
    _set(cancelled_flight=f)
    return {
        "flight_number": f["flight_number"], "carrier": f["carrier"],
        "origin": f["origin"], "destination": f["destination"], "depart": f["depart"],
        "spoken": (f"Your {f['carrier']} flight {f['flight_number']} from "
                   f"{f['origin']} to {f['destination']} was cancelled."),
    }


class SearchReq(BaseModel):
    # Live overrides captured from the conversation; anything omitted falls back
    # to the voice-collected preferences.
    airline_preference: Optional[str] = None
    stops: Optional[str] = None                # nonstop | 1_stop | any
    preferred_time: Optional[str] = None       # early_morning|morning|afternoon|evening|red_eye
    cabin_class: Optional[str] = None
    max_budget: Optional[float] = None


@router.post("/agent/search-rebooking")
async def search_rebooking(req: SearchReq):
    """Tool: search_rebooking_options — real Sabre search, ranked by preferences."""
    f = _state["cancelled_flight"] or dict(DEFAULT_CANCELLED_FLIGHT)
    _set(cancelled_flight=f, status="searching")

    # Precedence: config default budget < saved profile < live conversation overrides.
    overrides = req.model_dump(exclude_none=True)
    prefs = {"max_budget": DEFAULT_MAX_BUDGET, **_flight_prefs(), **overrides}

    try:
        candidates = sabre.search_flights(f)
    except Exception as e:
        print(f"[rebooking] Sabre search failed: {e}")
        candidates = []

    ranked, relaxed = _apply_preferences(candidates, prefs) if candidates else ([], False)
    options = ranked[:MAX_OPTIONS]
    _set(options=options, status="presented")

    if not options:
        return {"ok": False, "options": [],
                "spoken": "I'm sorry, I couldn't find any alternative flights on that route right now."}

    return {
        "ok": True,
        "options": options,
        "applied_preferences": prefs,
        "spoken": _spoken_options(options, prefs, relaxed),
    }


class BookReq(BaseModel):
    flight_number: Optional[str] = None   # which option; defaults to the top match


@router.post("/agent/book")
async def book(req: BookReq):
    """
    Tool: book_selected_flight. HANDOFF SEAM to the team's real Sabre Create PNR.
    Until that's wired, returns a confirmation via sabre.book_flight (simulated
    unless SABRE_BOOKING_ENABLED). Replace the marked block with the team's call.
    """
    opts = _state["options"]
    chosen = next((o for o in opts if o.get("flight_number") == req.flight_number), None)
    chosen = chosen or (opts[0] if opts else None)
    if not chosen:
        return {"ok": False, "spoken": "I don't have a flight selected to book yet — let me search first."}

    _set(selected=chosen, status="booking")
    # --- TODO(team): replace with the real Create PNR booking call ---
    booking = sabre.book_flight(chosen)
    # -----------------------------------------------------------------
    _set(status="booked")
    return {
        "ok": True, "confirmation": booking["pnr"], "flight": chosen,
        "spoken": (f"You're all set — rebooked on {chosen['carrier']} flight "
                   f"{chosen['flight_number']}, confirmation {booking['pnr']}."),
    }


@router.get("/agent/rebooking-status")
async def rebooking_status():
    """For the web UI to poll the rebooking flow's progress."""
    with _lock:
        return dict(_state)

"""
Agent logic: the decision-making for the voice flow.

Three jobs:
    opening_line(old_flight)              -> str    what the agent says first
    interpret_response(user_text)         -> dict   did the user say yes?
    pick_flight(old_flight, candidates)   -> dict   choose the best replacement

Currently rule-based (no LLM) — keeps the demo dependency-free and deterministic.
Each function is a single, self-contained rule; swap any one for an LLM call
later (e.g. Claude) without touching the callers or the rest of the app.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. Opening line for the outbound call
# ---------------------------------------------------------------------------
def opening_line(old_flight: dict) -> str:
    when = _friendly_time(old_flight.get("depart", ""))
    dest = old_flight.get("destination", "your destination")
    return (
        f"Hi, this is Tailwind calling about your flight {old_flight.get('flight_number','')}. "
        f"Unfortunately your {when} flight to {dest} was just cancelled. "
        f"I can rebook you on the next available flight right now — want me to do that?"
    )


# ---------------------------------------------------------------------------
# 2. Interpret the traveler's spoken response
# ---------------------------------------------------------------------------
def interpret_response(user_text: str) -> dict:
    """Returns {"intent": "confirm"|"decline"|"unclear", "reply": "<spoken reply>"}."""
    t = (user_text or "").lower()
    yes = ("yes", "yeah", "yep", "sure", "please", "go ahead", "book", "do it", "okay", "ok")
    no = ("no", "don't", "do not", "stop", "cancel", "not now", "nope")
    if any(w in t for w in no):
        return {"intent": "decline", "reply": "No problem — I won't make any changes. Take care."}
    if any(w in t for w in yes):
        return {"intent": "confirm", "reply": "Great, booking the next available flight now — one moment."}
    return {"intent": "unclear", "reply": "Sorry, should I rebook you on the next available flight? Yes or no?"}


# ---------------------------------------------------------------------------
# 3. Pick the best replacement flight from Sabre results
# ---------------------------------------------------------------------------
def pick_flight(old_flight: dict, candidates: list[dict]) -> dict:
    """Returns {"flight": <chosen candidate>, "reason": "<why>"}."""
    if not candidates:
        return {"flight": None, "reason": "No alternative flights were available."}
    # Prefer soonest arrival, then fewest stops, then price.
    chosen = sorted(
        candidates,
        key=lambda c: (c.get("arrive", ""), c.get("stops", 99), c.get("price", 1e9)),
    )[0]
    return {"flight": chosen, "reason": "Soonest arrival with the fewest stops."}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _friendly_time(iso: str) -> str:
    # "2026-07-18T18:00:00" -> "6:00 PM"
    try:
        hhmm = iso.split("T")[1][:5]
        h, m = int(hhmm[:2]), hhmm[3:5]
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m} {ampm}"
    except (IndexError, ValueError):
        return "scheduled"

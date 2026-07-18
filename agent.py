"""
Claude orchestration: the "brain" of the voice agent.

Three jobs:
    opening_line(old_flight)              -> str    what the agent says first
    interpret_response(user_text)         -> dict   did the user say yes?
    pick_flight(old_flight, candidates)   -> dict   choose the best replacement

Everything degrades gracefully: if no ANTHROPIC_API_KEY / DEMO_MODE is on, we
use simple rule-based fallbacks so the demo still runs. When Claude is available
it makes the interpretation + choice smarter.
"""
from __future__ import annotations

import os
import json

try:
    from anthropic import Anthropic
except ImportError:  # anthropic not installed yet
    Anthropic = None

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")


def _demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")


def _client():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if _demo_mode() or not key or Anthropic is None:
        return None
    return Anthropic(api_key=key)


def _ask_claude(system: str, user: str) -> str | None:
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception as e:  # never let the LLM break the demo
        print(f"[agent] Claude call failed, using fallback: {e}")
        return None


# ---------------------------------------------------------------------------
# 1. Opening line for the outbound call
# ---------------------------------------------------------------------------
def opening_line(old_flight: dict) -> str:
    when = _friendly_time(old_flight.get("depart", ""))
    dest = old_flight.get("destination", "your destination")
    fallback = (
        f"Hi, this is Tailwind calling about your flight {old_flight.get('flight_number','')}. "
        f"Unfortunately your {when} flight to {dest} was just cancelled. "
        f"I can rebook you on the next available flight right now — want me to do that?"
    )
    out = _ask_claude(
        system=(
            "You are Tailwind, a proactive airline assistant making a brief, warm outbound "
            "phone call. Write ONE short spoken opener (2-3 sentences). Tell the traveler their "
            "flight was cancelled and offer to rebook them on the next available flight now. "
            "Sound calm and helpful, not robotic. Return only the spoken words."
        ),
        user=f"Cancelled flight details:\n{json.dumps(old_flight, indent=2)}",
    )
    return out or fallback


# ---------------------------------------------------------------------------
# 2. Interpret the traveler's spoken response
# ---------------------------------------------------------------------------
def interpret_response(user_text: str) -> dict:
    """Returns {"intent": "confirm"|"decline"|"unclear", "reply": "<spoken reply>"}."""
    fallback = _rule_based_intent(user_text)
    out = _ask_claude(
        system=(
            "You classify a traveler's spoken reply to 'can I rebook you on the next flight?'. "
            "Respond with ONLY a JSON object: "
            '{"intent": "confirm" | "decline" | "unclear", "reply": "<one short spoken sentence>"}. '
            "confirm = they want the rebooking. decline = they don't. unclear = ambiguous."
        ),
        user=f'Traveler said: "{user_text}"',
    )
    if out:
        try:
            data = json.loads(out[out.find("{"): out.rfind("}") + 1])
            if data.get("intent") in ("confirm", "decline", "unclear"):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return fallback


def _rule_based_intent(user_text: str) -> dict:
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

    fallback = _rule_based_pick(candidates)
    out = _ask_claude(
        system=(
            "You help a stranded traveler pick the best replacement flight. Prefer the soonest "
            "arrival, then fewest stops, then price. Respond with ONLY JSON: "
            '{"flight_number": "<one of the candidates>", "reason": "<one short sentence>"}.'
        ),
        user=(
            f"Cancelled flight:\n{json.dumps(old_flight, indent=2)}\n\n"
            f"Candidates:\n{json.dumps(candidates, indent=2)}"
        ),
    )
    if out:
        try:
            data = json.loads(out[out.find("{"): out.rfind("}") + 1])
            chosen = next(
                (c for c in candidates if c["flight_number"] == data.get("flight_number")), None
            )
            if chosen:
                return {"flight": chosen, "reason": data.get("reason", "")}
        except (json.JSONDecodeError, ValueError):
            pass
    return fallback


def _rule_based_pick(candidates: list[dict]) -> dict:
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

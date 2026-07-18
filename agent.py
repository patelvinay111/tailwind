"""
Tailwind AI — Booking agent powered by Claude tool-use.

This is the BOOKING component of the Tailwind system. It handles:
  - Search flights (Sabre Flight Shop Lite)
  - Search hotels (Sabre Hotel Search + Rates)
  - Confirm prices before booking
  - Book the trip
  - Update the UI (show cards, itinerary)

PLUGGABLE DESIGN:
  - Preferences are passed in as a dict — source doesn't matter (JSON, CSV, DB)
  - sabre.py is a shared utility (cancellation agent uses it too)
  - vocalbridge.py is a shared utility (any agent can use voice)
  - This module exposes run_conversation_turn() as its main entry point

In DEMO_MODE or without an API key, falls back to simple rule-based responses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

import sabre

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# ---------------------------------------------------------------------------
# Preferences loader (pluggable — teammate can swap this to read CSV)
# ---------------------------------------------------------------------------

_PREFERENCES_CACHE: dict | None = None


def load_preferences(force_reload: bool = False) -> dict:
    """
    Load traveler preferences. Currently reads from preferences.json.
    Teammate will swap this to read from CSV or other source.

    The rest of the code only calls this function — never reads files directly.
    """
    global _PREFERENCES_CACHE
    if _PREFERENCES_CACHE is not None and not force_reload:
        return _PREFERENCES_CACHE

    # Try JSON first (our default)
    json_path = Path(__file__).parent / "preferences.json"
    if json_path.exists():
        _PREFERENCES_CACHE = json.loads(json_path.read_text())
        return _PREFERENCES_CACHE

    # Try CSV (teammate's format) — they'll implement csv_to_preferences()
    csv_path = Path(__file__).parent / "preferences.csv"
    if csv_path.exists():
        try:
            from preferences_loader import csv_to_preferences
            _PREFERENCES_CACHE = csv_to_preferences(csv_path)
            return _PREFERENCES_CACHE
        except ImportError:
            pass

    _PREFERENCES_CACHE = {}
    return _PREFERENCES_CACHE


# ---------------------------------------------------------------------------
# Tool definitions for Claude
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "search_flights",
        "description": "Search for available flights between two airports on a given date. Prioritize the traveler's preferred airlines and nonstop preference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Origin airport code (e.g., SFO)"},
                "destination": {"type": "string", "description": "Destination airport code (e.g., AUS)"},
                "departure_date": {"type": "string", "description": "Departure date YYYY-MM-DD"},
                "return_date": {"type": "string", "description": "Return date YYYY-MM-DD (optional for one-way)"},
                "cabin": {"type": "string", "enum": ["Economy", "Business", "First"], "description": "Cabin class"},
                "max_results": {"type": "integer", "description": "Max number of results to return (default 5)"},
            },
            "required": ["origin", "destination", "departure_date"],
        },
    },
    {
        "name": "search_hotels",
        "description": "Search for hotels near a location. Prioritize the traveler's preferred hotel chains and budget.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name, address, or airport code"},
                "check_in": {"type": "string", "description": "Check-in date YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "Check-out date YYYY-MM-DD"},
                "guests": {"type": "integer", "description": "Number of guests (default 1)"},
                "max_price_per_night": {"type": "number", "description": "Maximum price per night in USD"},
            },
            "required": ["location", "check_in", "check_out"],
        },
    },
    {
        "name": "get_hotel_rates",
        "description": "Get detailed room rates for a specific hotel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hotel_code": {"type": "string", "description": "Hotel property code from search results"},
                "check_in": {"type": "string", "description": "Check-in date YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "Check-out date YYYY-MM-DD"},
                "guests": {"type": "integer", "description": "Number of guests (default 1)"},
            },
            "required": ["hotel_code", "check_in", "check_out"],
        },
    },
    {
        "name": "confirm_price",
        "description": "Verify the current price of a selected flight or hotel before booking. Call this after the user picks an option.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_type": {"type": "string", "enum": ["flight", "hotel"]},
                "offer_id": {"type": "string", "description": "Offer ID or rate key from search results"},
            },
            "required": ["item_type", "offer_id"],
        },
    },
    {
        "name": "book_trip",
        "description": "Book the confirmed flights and/or hotel. Only call this AFTER the user explicitly confirms they want to book.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flights": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of flight objects to book",
                },
                "hotel": {"type": "object", "description": "Hotel object to book (optional)"},
            },
            "required": ["flights"],
        },
    },
    {
        "name": "update_display",
        "description": "Update the user's screen with option cards or itinerary changes. Use this to show flight/hotel options as cards, add items to itinerary, or show the trip summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["show_flight_options", "show_hotel_options", "add_to_itinerary", "show_summary", "clear_options", "booking_confirmed"],
                },
                "data": {"type": "object", "description": "Payload for the action"},
            },
            "required": ["action", "data"],
        },
    },
]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt(preferences: dict) -> str:
    prefs_str = json.dumps(preferences, indent=2)
    return f"""You are Tailwind, a friendly and efficient voice travel assistant. You help travelers plan and book complete trips through natural conversation.

TRAVELER PREFERENCES (use these proactively):
{prefs_str}

PERSONALITY:
- Warm, concise, conversational — you're speaking out loud on a voice call
- Naturally mention when you're using their preferences ("Since you usually fly Delta...")
- Keep responses to 2-3 sentences max (this is voice, not text)
- Confirm details before booking
- Present the best options based on their preferences first

RULES:
- Use the traveler's home airport as origin unless they specify otherwise
- Prioritize their preferred airlines and hotel chains in results
- Respect budget constraints without being asked
- NEVER book without explicit confirmation from the user
- When presenting options, lead with their preferred choices
- Always call update_display to show option cards when you have search results
- Always call update_display with show_summary before booking

FLOW:
1. Greet by name, acknowledge their preferences are loaded
2. Ask where they're going (or respond if they already said it)
3. Search flights → call update_display to show cards → present top 3 verbally
4. User picks → call update_display to add_to_itinerary → ask about hotels
5. Search hotels → call update_display to show cards → present top options
6. User picks → call update_display to add_to_itinerary
7. Call update_display with show_summary → read back total → ask for confirmation
8. User confirms → call book_trip → call update_display with booking_confirmed
9. Share confirmation numbers, wish them a great trip

IMPORTANT: You are speaking on a phone/voice call. Do NOT use markdown, bullet points, or formatting. Speak naturally in short sentences."""


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _execute_tool(name: str, args: dict, preferences: dict) -> str:
    """Execute a tool call and return the result as a string for Claude."""
    if name == "search_flights":
        results = sabre.search_flights_v2(
            origin=args["origin"],
            destination=args["destination"],
            departure_date=args["departure_date"],
            return_date=args.get("return_date"),
            cabin=args.get("cabin", preferences.get("flight_preferences", {}).get("cabin_class", "Economy")),
            max_results=args.get("max_results", 5),
        )
        return json.dumps({"flights": results})

    elif name == "search_hotels":
        results = sabre.search_hotels(
            location=args["location"],
            check_in=args["check_in"],
            check_out=args["check_out"],
            guests=args.get("guests", 1),
            max_price=args.get("max_price_per_night", preferences.get("hotel_preferences", {}).get("budget_per_night_usd")),
        )
        return json.dumps({"hotels": results})

    elif name == "get_hotel_rates":
        results = sabre.get_hotel_rates(
            hotel_code=args["hotel_code"],
            check_in=args["check_in"],
            check_out=args["check_out"],
            guests=args.get("guests", 1),
        )
        return json.dumps({"rates": results})

    elif name == "confirm_price":
        result = sabre.check_price(
            item_type=args["item_type"],
            offer_id=args["offer_id"],
        )
        return json.dumps(result)

    elif name == "book_trip":
        traveler = preferences.get("traveler", {})
        result = sabre.book_trip(
            flights=args.get("flights", []),
            hotel=args.get("hotel"),
            traveler_name=f"{traveler.get('name', 'DEMO')}",
            loyalty=preferences.get("flight_preferences", {}).get("loyalty_programs", []),
        )
        return json.dumps(result)

    elif name == "update_display":
        # This is a UI-only tool — we return success and the main.py handler
        # will extract the action/data from the tool call to update frontend state.
        return json.dumps({"ok": True, "action": args["action"], "data": args.get("data", {})})

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Main conversation loop
# ---------------------------------------------------------------------------

def _demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")


def _client():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    # Fall back to demo if: no key, placeholder key, or anthropic not installed
    if not key or "xxxx" in key or Anthropic is None:
        return None
    return Anthropic(api_key=key)


def run_conversation_turn(messages: list[dict], user_text: str, preferences: dict | None = None) -> dict:
    """
    Process one turn of conversation.

    Args:
        messages: Full conversation history (Claude messages format)
        user_text: What the user just said
        preferences: Traveler preferences (loaded from file if not provided)

    Returns:
        {
            "reply": str,              # What the agent should say
            "messages": list,          # Updated conversation history
            "display_updates": list,   # UI actions to execute [{action, data}]
            "booking": dict | None,    # Booking result if trip was booked
        }
    """
    if preferences is None:
        preferences = load_preferences()

    messages.append({"role": "user", "content": user_text})

    client = _client()
    if client is None:
        result = _demo_conversation_turn(messages, user_text, preferences)
        return result

    system = _build_system_prompt(preferences)
    display_updates = []
    booking = None

    # Tool-use loop: Claude may call multiple tools before responding
    while True:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        # Collect text and tool use blocks
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Check if Claude wants to use tools
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]
        if not tool_uses:
            # No tool calls — extract the text reply
            reply = "".join(b.text for b in assistant_content if b.type == "text").strip()
            break

        # Execute each tool call
        tool_results = []
        for tool_use in tool_uses:
            result_str = _execute_tool(tool_use.name, tool_use.input, preferences)

            # Capture display updates and booking results
            if tool_use.name == "update_display":
                display_updates.append(tool_use.input)
            elif tool_use.name == "book_trip":
                booking = json.loads(result_str)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})
        # Loop continues — Claude will process tool results and may call more tools or respond

    return {
        "reply": reply,
        "messages": messages,
        "display_updates": display_updates,
        "booking": booking,
    }


# ---------------------------------------------------------------------------
# Demo mode fallback (no API key)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Backward-compat: disruption flow functions (main.py still calls these)
# ---------------------------------------------------------------------------

def opening_line(flight: dict) -> str:
    """Generate the opening line for the disruption outbound call."""
    client = _client()
    if client is None:
        return (
            f"Hi, this is Tailwind, your travel assistant. I'm calling because your "
            f"{flight['carrier']} flight {flight['flight_number']} from {flight['origin']} "
            f"to {flight['destination']} has been cancelled. I've already found some "
            f"alternative flights for you. Would you like me to rebook you on the next available one?"
        )

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=200,
        system="You are a travel assistant making an outbound phone call. Be warm, brief, and clear. One short paragraph.",
        messages=[{"role": "user", "content": (
            f"Generate the opening line for a call to a traveler whose flight was cancelled:\n"
            f"Flight: {flight['carrier']} {flight['flight_number']}\n"
            f"Route: {flight['origin']} → {flight['destination']}\n"
            f"Was scheduled: {flight['depart']}\n"
            f"Tell them it's cancelled and ask if they'd like you to rebook them on an alternative."
        )}],
    )
    return resp.content[0].text.strip()


def interpret_response(text: str) -> dict:
    """Classify user speech as confirm/decline/unclear for the disruption flow."""
    t = text.lower()
    yes_words = ("yes", "yeah", "yep", "sure", "please", "book", "go ahead", "do it", "okay", "ok", "absolutely")
    no_words = ("no", "don't", "cancel", "stop", "nevermind", "never mind", "decline")

    if any(w in t for w in yes_words):
        return {"intent": "confirm", "reply": "Great — finding you the best alternative now."}
    if any(w in t for w in no_words):
        return {"intent": "decline", "reply": "No problem. Let me know if you change your mind."}
    return {"intent": "unclear", "reply": "I didn't quite catch that. Would you like me to rebook you on the next available flight?"}


def pick_flight(old_flight: dict, candidates: list[dict]) -> dict:
    """Let Claude (or rules) pick the best alternative flight."""
    if not candidates:
        return {"flight": None, "reason": "No alternatives available."}

    client = _client()
    if client is None:
        # Rule-based: prefer nonstop, then cheapest
        nonstop = [f for f in candidates if f.get("stops", 99) == 0]
        best = min(nonstop or candidates, key=lambda f: f.get("price", 9999))
        reason = "Nonstop, lowest fare" if best.get("stops", 99) == 0 else "Lowest fare available"
        return {"flight": best, "reason": reason}

    prompt = (
        f"Original cancelled flight: {old_flight['carrier']} {old_flight['flight_number']} "
        f"{old_flight['origin']}→{old_flight['destination']} at {old_flight['depart']}, ${old_flight['price']}\n\n"
        f"Alternatives:\n"
    )
    for i, c in enumerate(candidates):
        prompt += f"  {i+1}. {c.get('carrier','')} {c['flight_number']} departs {c['depart']} "
        prompt += f"arrives {c['arrive']} | {c.get('stops',0)} stops | ${c['price']}\n"
    prompt += "\nPick the best alternative. Prefer nonstop, similar departure time, reasonable price. Reply with JUST the number and a short reason."

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = resp.content[0].text.strip()

    # Parse the number from Claude's response
    for i, c in enumerate(candidates):
        if str(i + 1) in answer.split()[0] if answer else "":
            reason_text = answer[answer.find(" "):].strip() if " " in answer else "Best available option"
            return {"flight": c, "reason": reason_text}

    # Fallback to first candidate
    return {"flight": candidates[0], "reason": answer or "Best available option"}


# ---------------------------------------------------------------------------
# Demo mode fallback (no API key)
# ---------------------------------------------------------------------------

def _demo_conversation_turn(messages: list[dict], user_text: str, preferences: dict) -> dict:
    """Simple rule-based fallback for demo mode."""
    t = user_text.lower()
    name = preferences.get("traveler", {}).get("name", "there")
    display_updates = []
    booking = None

    # First message (greeting)
    if len(messages) <= 1:
        reply = (
            f"Hey {name}! I'm Tailwind, your travel assistant. "
            f"I've got your preferences loaded — you like Delta, aisle seats, and Hilton hotels. "
            f"Where are we headed?"
        )
    # Flight search trigger
    elif any(w in t for w in ("fly", "flight", "austin", "trip", "go to", "travel")):
        flights = sabre.search_flights_v2("SFO", "AUS", "2026-07-25", cabin="Economy")
        display_updates.append({
            "action": "show_flight_options",
            "data": {"flights": flights},
        })
        reply = (
            f"Nice — looking for flights from SFO to Austin. "
            f"Since you prefer nonstop and Delta, I prioritized those. "
            f"I found {len(flights)} options — the best is {flights[0]['carrier']} "
            f"at ${flights[0]['price']:.0f}. Check the cards on your screen!"
        )
    # Hotel search trigger
    elif any(w in t for w in ("hotel", "stay", "room", "accommodation")):
        hotels = sabre.search_hotels("Austin, TX", "2026-07-25", "2026-07-27")
        display_updates.append({
            "action": "show_hotel_options",
            "data": {"hotels": hotels},
        })
        reply = (
            f"Looking for hotels in Austin... I'm checking Hilton and Marriott first. "
            f"Found a {hotels[0]['name']} at ${hotels[0]['price_per_night']:.0f}/night. "
            f"Options are on your screen!"
        )
    # Booking confirmation
    elif any(w in t for w in ("book", "confirm", "yes", "do it", "go ahead")):
        booking = sabre.book_trip(
            flights=[{"flight_number": "DL1420", "origin": "SFO", "destination": "AUS"}],
            hotel={"name": "Hilton Garden Inn", "hotel_code": "HGI-AUS"},
            traveler_name=name,
        )
        display_updates.append({
            "action": "booking_confirmed",
            "data": booking,
        })
        reply = (
            f"Done! I've booked everything. "
            f"Your flight confirmation is {booking.get('flight_pnr', 'DL-XY7Q2L')} "
            f"and hotel confirmation is {booking.get('hotel_confirmation', 'HH-8832K')}. "
            f"Have an amazing trip, {name}!"
        )
    # Selection
    elif any(w in t for w in ("first", "delta", "hilton", "take", "that one", "pick")):
        display_updates.append({
            "action": "add_to_itinerary",
            "data": {"item": "selected"},
        })
        reply = "Great choice! I've added that to your itinerary. What else do you need?"
    # Decline
    elif any(w in t for w in ("no", "cancel", "never mind", "stop")):
        reply = "No problem! Let me know if you change your mind or want to plan something else."
    # Fallback
    else:
        reply = f"I can help you search flights, find hotels, or book a trip. What would you like to do?"

    messages.append({"role": "assistant", "content": reply})

    return {
        "reply": reply,
        "messages": messages,
        "display_updates": display_updates,
        "booking": booking,
    }

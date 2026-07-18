"""
MCP server — exposes Tailwind's API endpoints as Model Context Protocol tools,
so a Vocal Bridge agent (or any MCP client) can integrate via MCP instead of
Custom HTTP Tools.

Mounted into the FastAPI app at /mcp (SSE transport). A VB "MCP server" URL then is:
    https://<host>/mcp/sse

Each tool proxies to the app's own HTTP endpoint (APP_BASE_URL), so the business
logic stays in ONE place (rebooking.py / main.py) and this file never diverges —
add a new endpoint there and just add a thin wrapper here.

Does NOT touch the agent config — you wire this into the agent later (VB dashboard
> Add MCP server, or `vb config set --mcp-servers-file ...`).
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8787").rstrip("/")

# The MCP SDK's DNS-rebinding protection validates the Host header and, by
# default, only allows localhost — so hitting it via the EC2 hostname returns
# "Invalid Host header". Turn it off so VB (or any client) connects with JUST
# the URL, no custom Host header. Access control here is the EC2 security group.
mcp = FastMCP(
    "tailwind",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{APP_BASE_URL}{path}", params=params or {})
        return r.json()


async def _post(path: str, body: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(f"{APP_BASE_URL}{path}", json=body or {})
        return r.json()


# ---------------------------------------------------------------------------
# Disruption / rebooking (our flow)
# ---------------------------------------------------------------------------
@mcp.tool()
async def get_cancellation_context() -> dict:
    """Get the traveler's COMPLETE itinerary — passenger, every flight and its
    status, and which flight was cancelled. Call at the start of a disruption call
    so you know whose trip this is and what broke."""
    return await _get("/agent/context")


@mcp.tool()
async def trigger_cancellation(phone_number: Optional[str] = None) -> dict:
    """Mark the itinerary's flight cancelled in our records and place the outbound
    call to the traveler. phone_number overrides the itinerary's number."""
    body = {"phone_number": phone_number} if phone_number else {}
    return await _post("/agent/cancellation-trigger", body)


@mcp.tool()
async def search_rebooking_options(
    airline_preference: Optional[str] = None,
    stops: Optional[str] = None,
    preferred_time: Optional[str] = None,
    cabin_class: Optional[str] = None,
    max_budget: Optional[float] = None,
) -> dict:
    """Search Sabre for alternative flights on the cancelled route, ranked by the
    traveler's preferences. Pass any preference the traveler states (stops:
    nonstop|1_stop|any; preferred_time: early_morning|morning|afternoon|evening|
    red_eye); omit the rest — they fall back to the saved profile."""
    body = {k: v for k, v in dict(
        airline_preference=airline_preference, stops=stops,
        preferred_time=preferred_time, cabin_class=cabin_class,
        max_budget=max_budget,
    ).items() if v is not None}
    return await _post("/agent/search-rebooking", body)


@mcp.tool()
async def book_selected_flight(flight_number: Optional[str] = None) -> dict:
    """Book the rebooking option the traveler agreed to (defaults to the best
    match). Call only after they clearly confirm. Returns a confirmation code."""
    body = {"flight_number": flight_number} if flight_number else {}
    return await _post("/agent/book", body)


@mcp.tool()
async def get_rebooking_status() -> dict:
    """Get the current live itinerary and rebooking status."""
    return await _get("/agent/rebooking-status")


@mcp.tool()
async def reset_rebooking() -> dict:
    """Reset the itinerary back to the pristine sample (confirmed, not cancelled).
    Useful between test runs."""
    return await _post("/agent/rebooking-reset")


# ---------------------------------------------------------------------------
# Preferences (voice-collected trip/flight/hotel/food profile)
# ---------------------------------------------------------------------------
@mcp.tool()
async def get_preferences() -> dict:
    """Get the traveler's saved trip/flight/hotel/food preferences and completion status."""
    return await _get("/preferences")


@mcp.tool()
async def update_preference(category: str, field: str, value: object) -> dict:
    """Set one preference the traveler states. category is one of: trip, flight,
    hotel, food. Example fields — flight: stops, max_budget, preferred_time,
    cabin_class, airline_preference; trip: origin, destination, departure_date,
    number_of_travelers; hotel: room_type, max_budget_per_night; food: diet_type."""
    return await _post("/preferences/update", {"category": category, "field": field, "value": value})


@mcp.tool()
async def confirm_preferences() -> dict:
    """Mark the collected preferences as confirmed by the traveler."""
    return await _post("/preferences/confirm")


@mcp.tool()
async def mark_preferences_ready() -> dict:
    """Mark preference collection complete / ready to act on."""
    return await _post("/preferences/ready")


@mcp.tool()
async def invalidate_preferences(reason: str = "") -> dict:
    """Invalidate the collected preferences (e.g. the traveler changed their mind)."""
    return await _post("/preferences/invalidate", {"reason": reason})


@mcp.tool()
async def reset_preferences() -> dict:
    """Clear all collected preferences back to empty."""
    return await _post("/preferences/reset")


# ASGI app for mounting into FastAPI (SSE transport at /mcp/sse).
sse_app = mcp.sse_app()

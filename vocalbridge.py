"""
Vocal Bridge integration.

- trigger_call(to_number, ...)   -> start an OUTBOUND phone call (verified contract)
- get_webrtc_token(name)         -> mint a browser WebRTC/LiveKit token
- parse_webhook(payload)         -> normalize inbound transcript webhook events

Real API host is vocalbridgeai.com/api (api.vocalbridge.ai does NOT resolve).
The account API key requires the X-Agent-Id header on BOTH the call and token
requests — without it VB returns 401.
"""
from __future__ import annotations

import os
import httpx

VB_API_KEY = os.getenv("VOCALBRIDGE_API_KEY", "")
VB_BASE_URL = os.getenv("VOCALBRIDGE_BASE_URL", "https://vocalbridgeai.com/api")
VB_TOKEN_URL = os.getenv("VOCALBRIDGE_TOKEN_URL", "https://vocalbridgeai.com/api/v1/token")
VB_AGENT_ID = os.getenv("VOCALBRIDGE_AGENT_ID", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8787")

# vocalbridgeai.com is behind Cloudflare, which 403s default library User-Agents.
_UA = "curl/8.7.1"


def _demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")


def trigger_call(to_number: str, opening_line: str | None = None, context: dict | None = None) -> dict:
    """
    Start an OUTBOUND phone call via POST {VB_BASE_URL}/v1/calls.
    Verified contract: body {"phone_number": "<E.164>"} + headers X-API-Key and
    X-Agent-Id. VB's pre-configured agent (prompt + tools) runs the whole
    conversation, so we only say WHO to call. `opening_line`/`context` are accepted
    for caller compatibility but not sent — the agent's own prompt/greeting drives it.
    """
    if not (VB_API_KEY and VB_AGENT_ID):
        print(f"[vocalbridge] missing VB creds — pretend-calling {to_number}")
        return {"call_id": "demo-call-001", "status": "dialing", "demo": True}

    resp = httpx.post(
        f"{VB_BASE_URL}/v1/calls",
        headers={
            "X-API-Key": VB_API_KEY,
            "X-Agent-Id": VB_AGENT_ID,
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
        json={"phone_number": to_number},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "call_id": data.get("call_id") or data.get("id") or data.get("session_id"),
        "status": data.get("status", "dialing"),
        "demo": False,
    }


def get_webrtc_token(participant_name: str = "User") -> dict:
    """
    Mint a LiveKit token for in-browser voice. Frontend calls POST /api/voice-token,
    we proxy to VB with our API key. Returns:
      {livekit_url, token, room_name, participant_identity, expires_in, agent_mode}

    The account API key REQUIRES the X-Agent-Id header (without it VB 401s).
    """
    if not VB_API_KEY:
        return {"error": "No VOCALBRIDGE_API_KEY set", "demo": True}

    headers = {"X-API-Key": VB_API_KEY, "Content-Type": "application/json", "User-Agent": _UA}
    if VB_AGENT_ID:
        headers["X-Agent-Id"] = VB_AGENT_ID
    resp = httpx.post(
        VB_TOKEN_URL,
        headers=headers,
        json={"participant_name": participant_name},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def parse_webhook(payload: dict) -> dict:
    """
    Normalize whatever Vocal Bridge POSTs into a small event we can act on:

        {"type": "transcript" | "call_ended" | "other",
         "role": "user" | "agent" | None,
         "text": "<what the user said>",
         "call_id": "...",
         "raw": <original payload>}
    """
    event_type = (
        payload.get("event")
        or payload.get("type")
        or payload.get("event_type")
        or "other"
    )
    role = payload.get("speaker") or payload.get("role")
    text = (
        payload.get("text")
        or payload.get("transcript")
        or payload.get("message")
        or ""
    )
    call_id = payload.get("call_id") or payload.get("id")

    if event_type in ("transcript", "user_message", "message", "speech"):
        norm_type = "transcript"
    elif event_type in ("call_ended", "hangup", "completed", "call.completed"):
        norm_type = "call_ended"
    else:
        norm_type = "other"

    return {
        "type": norm_type,
        "role": role,
        "text": text,
        "call_id": call_id,
        "raw": payload,
    }

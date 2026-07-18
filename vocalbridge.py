"""
Vocal Bridge integration.

Architecture: VB runs a MANAGED voice agent (its own LLM) that holds the call
and calls OUR tools (the /agent/* endpoints) mid-conversation. We don't script
the dialogue — VB does. Our job here is just to (a) kick off the call and
(b) mint browser tokens for the WebRTC transport.

Public functions:
    trigger_call(to_number, context)          -> dict   start an OUTBOUND phone call
    mint_browser_token(participant_name)       -> dict   token for the in-browser SDK
    parse_webhook(payload)                     -> dict   normalized transcript event
                                                         (optional: live transcript UI)

Setup on the Vocal Bridge side (see vb/agent-prompt.md + vb/api-tools.json):
    vb prompt set --file vb/agent-prompt.md
    vb config set --api-tools-file vb/api-tools.json   # point URLs at your ngrok
    vb config set --outbound-enabled true --accept-outbound-tos --outbound-wait-for-user true

In DEMO_MODE, calls are faked (no dial, no token request). Set DEMO_MODE=false
and fill VOCALBRIDGE_* in .env to go live; PUBLIC_BASE_URL must be your ngrok URL
so VB can reach the tool endpoints and (optionally) the webhook.

Auth note: the token endpoint uses the `X-API-Key: vb_...` header (per VB docs),
not a Bearer token. Adjust the outbound-call endpoint/body to match the exact
REST shape from the on-site docs (marked TODO below).
"""
import os
import httpx

VB_API_KEY = os.getenv("VOCALBRIDGE_API_KEY", "")
VB_BASE_URL = os.getenv("VOCALBRIDGE_BASE_URL", "https://api.vocalbridge.ai")
VB_TOKEN_URL = os.getenv("VOCALBRIDGE_TOKEN_URL", "https://vocalbridgeai.com/api/v1/token")
VB_AGENT_ID = os.getenv("VOCALBRIDGE_AGENT_ID", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8787")


def _demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")


def trigger_call(to_number: str, context: dict) -> dict:
    """
    Start an OUTBOUND phone call. VB's agent (configured with vb/agent-prompt.md
    + api-tools.json) runs the conversation and calls our /agent/* tools — so we
    don't pass a script here, just who to call and pass-through context.
    """
    if _demo_mode():
        print(f"[vocalbridge] DEMO_MODE: pretend-calling {to_number}")
        return {"call_id": "demo-call-001", "status": "dialing", "demo": True}

    # TODO(on-site): confirm the outbound-call endpoint + body. Per VB docs the
    # agent is pre-configured (prompt + tools), so a call just needs the agent id
    # and destination number. The `vb call <number>` CLI does this under the hood.
    body = {
        "agent_id": VB_AGENT_ID,
        "to": to_number,
        "metadata": context,   # correlate the call back to this demo run
    }
    resp = httpx.post(
        f"{VB_BASE_URL}/v1/calls",
        headers={"X-API-Key": VB_API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "call_id": data.get("call_id") or data.get("id"),
        "status": data.get("status", "dialing"),
        "demo": False,
    }


def mint_browser_token(participant_name: str = "Traveler") -> dict:
    """
    Mint a short-lived LiveKit token for the in-browser WebRTC transport.
    The frontend SDK connects with this. Keeps the API key server-side.
    Returns VB's token payload ({livekit_url, token, room_name, ...}).

    Not gated by DEMO_MODE — voice works whenever a VB key is present (voice and
    the Sabre demo are decoupled). The account key requires the X-Agent-Id header.
    """
    if not VB_API_KEY:
        return {"demo": True, "livekit_url": None, "token": None,
                "note": "No VOCALBRIDGE_API_KEY set — cannot mint a token."}

    headers = {"X-API-Key": VB_API_KEY, "Content-Type": "application/json"}
    if VB_AGENT_ID:
        headers["X-Agent-Id"] = VB_AGENT_ID
    resp = httpx.post(
        VB_TOKEN_URL,
        headers=headers,
        json={"participant_name": participant_name},
        timeout=20,
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

    TODO(on-site): map the real webhook field names. Vocal Bridge likely sends
    events like {"event": "transcript", "speaker": "user", "text": "..."} or
    similar — tweak the getters below once you see a real payload printed.
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

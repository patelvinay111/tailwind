"""
Vocal Bridge integration: trigger an outbound call + normalize inbound webhooks.

Public functions:
    trigger_call(to_number, opening_line, context) -> dict   starts the call
    parse_webhook(payload)                         -> dict   normalized event

In DEMO_MODE, trigger_call doesn't actually dial anyone — it just logs and
returns a fake call id. To drive the demo offline, POST a fake transcript to
/vocalbridge/webhook yourself (there's a curl example in the README/main.py).

Once you have real Vocal Bridge credentials on-site:
  1. Set DEMO_MODE=false and fill VOCALBRIDGE_* in .env.
  2. Make sure PUBLIC_BASE_URL points at your ngrok tunnel so Vocal Bridge can
     reach POST {PUBLIC_BASE_URL}/vocalbridge/webhook.
  3. Adjust the request body / webhook field names below to match their docs.
"""
import os
import httpx

VB_API_KEY = os.getenv("VOCALBRIDGE_API_KEY", "")
VB_BASE_URL = os.getenv("VOCALBRIDGE_BASE_URL", "https://api.vocalbridge.ai")
VB_AGENT_ID = os.getenv("VOCALBRIDGE_AGENT_ID", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8787")


def _demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")


def trigger_call(to_number: str, opening_line: str, context: dict) -> dict:
    """
    Place an outbound call. `opening_line` is what the agent says first (built by
    agent.py from Claude). `context` carries the itinerary so the webhook handler
    can correlate the call back to this demo run.
    """
    if _demo_mode():
        print(f"[vocalbridge] DEMO_MODE: pretend-calling {to_number}")
        print(f"[vocalbridge] agent would open with: {opening_line!r}")
        return {"call_id": "demo-call-001", "status": "dialing", "demo": True}

    # TODO(on-site): confirm endpoint + body with Vocal Bridge docs. Many voice
    # platforms expose exactly this "voice-ify" shape: an agent id, a destination
    # number, a first message, and a webhook URL for events/transcripts.
    body = {
        "agent_id": VB_AGENT_ID,
        "to": to_number,
        "first_message": opening_line,
        "webhook_url": f"{PUBLIC_BASE_URL}/vocalbridge/webhook",
        # Pass-through metadata so we can match the webhook to this run.
        "metadata": context,
    }
    resp = httpx.post(
        f"{VB_BASE_URL}/v1/calls",
        headers={"Authorization": f"Bearer {VB_API_KEY}", "Content-Type": "application/json"},
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

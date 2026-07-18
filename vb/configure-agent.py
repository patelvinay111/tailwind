#!/usr/bin/env python3
"""
Configure the Vocal Bridge agent from our repo — idempotent, re-runnable.

Pushes: system prompt (vb/agent-prompt.md), the 3 custom API tools (pointed at
PUBLIC_BASE_URL), greeting, hangup-enabled, web-search-off. Re-run this whenever
the public URL changes (tunnel restart or Render deploy).

    python vb/configure-agent.py                 # uses PUBLIC_BASE_URL from .env
    python vb/configure-agent.py https://xxx.onrender.com   # override base URL

Reads VOCALBRIDGE_API_KEY + VOCALBRIDGE_AGENT_ID from .env.
"""
from __future__ import annotations

import os
import sys
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://vocalbridgeai.com/api/v1/agent"
API_PROMPT = "https://vocalbridgeai.com/api/v1/agent/prompt"


def patch(url: str, payload: dict, key: str, agent_id: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "X-API-Key": key,
            "X-Agent-Id": agent_id,
            "Content-Type": "application/json",
            # vocalbridgeai.com sits behind Cloudflare, which blocks the default
            # urllib User-Agent (403 code 1010). Present a curl-like UA.
            "User-Agent": "curl/8.7.1",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def load_env() -> dict:
    env = {}
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def main() -> int:
    env = load_env()
    key = env.get("VOCALBRIDGE_API_KEY", "")
    agent_id = env.get("VOCALBRIDGE_AGENT_ID", "")
    base = (sys.argv[1] if len(sys.argv) > 1 else env.get("PUBLIC_BASE_URL", "")).rstrip("/")

    if not (key and agent_id and base):
        print("Missing VOCALBRIDGE_API_KEY / VOCALBRIDGE_AGENT_ID / PUBLIC_BASE_URL")
        return 1

    prompt = (ROOT / "vb" / "agent-prompt.md").read_text()

    api_tools = [
        {
            "id": "get_cancellation_context",
            "name": "get_cancellation_context",
            "description": "Get the traveler's cancelled flight details (flight number, route, "
                           "departure time) so the greeting is specific. Call once at the start "
                           "of the call, before speaking.",
            "method": "GET",
            "url": f"{base}/agent/context",
            "parameters": [],
        },
        {
            "id": "rebook_next_available_flight",
            "name": "rebook_next_available_flight",
            "description": "Search Sabre for the next available flight on the same route and rebook "
                           "the traveler on the best option. Call ONLY after the traveler clearly "
                           "agrees. Returns the new flight and a confirmation code to read back.",
            "method": "POST",
            "url": f"{base}/agent/rebook",
            "parameters": [],
        },
        {
            "id": "decline_rebooking",
            "name": "decline_rebooking",
            "description": "Record that the traveler declined to rebook. Call if they say no or not now.",
            "method": "POST",
            "url": f"{base}/agent/decline",
            "parameters": [],
        },
    ]

    payload = {
        "greeting": "Hi, this is Tailwind, your automated travel assistant, calling with an "
                    "important update about your flight. This call may be recorded.",
        "api_tools": api_tools,
        "hangup_enabled": True,
        "web_search_enabled": False,
        "background_enabled": True,
        "outbound_greeting": "Hi, this is Tailwind, your automated travel assistant, with an "
                             "important update about your flight.",
    }

    try:
        # System prompt lives on its own endpoint.
        patch(API_PROMPT, {"prompt": prompt}, key, agent_id)
        # Everything else on /agent.
        data = patch(API, payload, key, agent_id)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:400]}")
        return 1

    print(f"✓ Configured agent {agent_id} with base {base}")
    a = data.get("agent", data)
    print("  custom_prompt set   :", bool(a.get("custom_prompt")))
    print("  api_tools count     :", len(a.get("api_tools") or []))
    print("  hangup_enabled      :", a.get("hangup_enabled"))
    print("  web_search_enabled  :", a.get("web_search_enabled"))
    print("  greeting            :", (a.get("greeting") or "")[:60])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

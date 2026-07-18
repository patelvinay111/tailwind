# Implementation Plan: Tailwind AI MVP

## Architecture Overview

```
User speaks → Vocal Bridge (STT) → AI Agent query → POST /webhook
  → Load preferences.json
  → Append to conversation history
  → Call Claude (tool-use) with: system prompt + preferences + history + tools
  → Claude decides: tool call or direct response
  → Execute Sabre API if needed → return to Claude → formulate reply
  → Return spoken text to Vocal Bridge (TTS)
  → Update session state (itinerary, transcript, options)
  → Frontend polls /status → renders UI
```

---

## Tasks

### Phase 1: Core Backend (agent brain + Sabre APIs)

- [x] **1.1** Create `preferences.json` — full traveler profile ✅
- [x] **1.2** Rewrite `agent.py` — Claude tool-use conversation loop ✅
  - System prompt with travel agent persona + preferences injection
  - Tool definitions: search_flights, search_hotels, get_hotel_rates, confirm_price, book_trip, update_display
  - Conversation history management (messages list)
  - Tool execution dispatcher (routes tool calls to sabre.py)
  - Graceful fallback when no API key (demo mode)
  - Pluggable preferences loader (supports JSON now, CSV swap by teammate)
- [ ] **1.3** Expand `sabre.py` — new API functions
  - `search_flights_v2(origin, dest, date, cabin, max_results)` — calls Flight Shop Lite
  - `search_hotels(location, check_in, check_out, guests, radius)` — calls Hotel Search
  - `get_hotel_rates(hotel_code, check_in, check_out, guests)` — calls Hotel Rates
  - `check_flight_price(offer_id)` — calls Flight Check
  - `check_hotel_price(rate_key)` — calls Hotel Price Check
  - `book_trip(flights, hotel, traveler)` — calls Create Booking
  - Demo fallbacks for each with realistic fake data
- [ ] **1.4** Rewrite `main.py` — session-based conversation
  - Replace linear state machine with session dict (messages, itinerary, transcript, options)
  - `POST /conversation` — receives user text, runs agent loop, returns response + UI updates
  - `POST /vocalbridge/webhook` — same but from Vocal Bridge events
  - `POST /api/voice-token` — proxy for Vocal Bridge WebRTC token
  - `POST /select-option` — user clicks a card on screen
  - `GET /status` — full session state for frontend polling
  - `POST /reset` — start new trip
  - `POST /simulate-call` — trigger outbound call (keep existing)

### Phase 2: Voice Integration

- [ ] **2.1** Update `vocalbridge.py` — add WebRTC token proxy
  - `get_webrtc_token()` — calls VB /api/v1/token endpoint
  - Keep existing outbound call + webhook parsing
- [ ] **2.2** Configure Vocal Bridge agent (via CLI/plugin)
  - Create agent with style "Chatty"
  - Enable AI Agent mode (delegates to our backend)
  - Set system prompt for natural voice delivery
  - Configure client actions for UI updates

### Phase 3: Frontend

- [ ] **3.1** Rewrite `static/index.html` — two-column layout
  - Dark + gold premium theme (CSS variables)
  - Left panel: voice widget area + transcript
  - Right panel: option cards area + itinerary builder
  - Responsive (stack on mobile)
- [ ] **3.2** Landing state
  - Hero text + "Start Planning" button + "Call Me" button
  - Premium branding
- [ ] **3.3** Voice widget integration
  - Embed Vocal Bridge JS SDK (`@vocalbridgeai/sdk`)
  - Connect on "Start Planning" click
  - Show connection state (connecting → connected → mic live)
  - Mute/unmute button
- [ ] **3.4** Transcript panel
  - Scrolling chat with agent (left) / user (right) messages
  - Auto-scroll to bottom on new messages
  - Polls /status for updates
- [ ] **3.5** Option cards
  - Flight card: airline logo, route, time, price, stops, cabin
  - Hotel card: name, location, price/night, rating
  - Clickable — sends POST /select-option
  - Highlight on hover, animate on selection
- [ ] **3.6** Itinerary builder
  - Cards appear as items are confirmed
  - Running total price
  - Confirmation numbers shown after booking
- [ ] **3.7** Trip summary / confirmation
  - Full trip summary card with total
  - "Confirm & Book" + "Cancel" buttons
  - Loading state during booking
  - Success state with confirmation numbers

### Phase 4: Polish & Demo Prep

- [ ] **4.1** End-to-end test in DEMO_MODE (no credentials)
- [ ] **4.2** End-to-end test with real Vocal Bridge (WebRTC in browser)
- [ ] **4.3** End-to-end test with outbound call mode
- [ ] **4.4** Edge cases: vague requests, changes, cancellations
- [ ] **4.5** Update `.env.example` with new vars
- [ ] **4.6** Update `CLAUDE.md` with final architecture
- [ ] **4.7** Update `README.md` with new setup/run instructions

---

## File Change Map

| File | Action | Description |
|------|--------|-------------|
| `preferences.json` | CREATE | Traveler profile + preferences |
| `agent.py` | REWRITE | Claude tool-use loop with history |
| `sabre.py` | EXTEND | Add Flight Shop Lite, Hotel Search, Hotel Rates, Price Check, Booking |
| `main.py` | REWRITE | Session-based routes, conversation endpoint, token proxy |
| `vocalbridge.py` | EXTEND | Add WebRTC token proxy function |
| `static/index.html` | REWRITE | Two-column UI, VB SDK, transcript, cards, itinerary |
| `.env.example` | UPDATE | Add VOCALBRIDGE_AGENT_ID |
| `requirements.txt` | NO CHANGE | anthropic + httpx + fastapi already there |

---

## Key Technical Decisions

1. **Claude as orchestrator** — tool-use drives the flow. No hardcoded state machine.
2. **Single session in memory** — no database. One traveler at a time (hackathon scope).
3. **Polling for frontend** — simple 1-second poll of /status. No WebSocket needed.
4. **Demo mode at every layer** — all Sabre calls have fake data fallback.
5. **VB AI Agent mode** — Vocal Bridge handles STT/TTS/turn-taking, delegates thinking to us.
6. **Click + voice** — option cards are clickable; clicks send to /select-option which feeds into the conversation as if the user said it.
7. **Pluggable architecture** — each component (booking agent, preferences, cancellation agent) is independent. Teammates work on separate pieces that plug in.

---

## Team Structure & Boundaries

| Person | Component | Interface |
|--------|-----------|-----------|
| **You** | Booking agent (this code) | `agent.py` reads preferences from a loader function, not directly from file |
| **Teammate 1** | Preferences knowledge base | Produces a CSV → we consume via a `load_preferences()` adapter |
| **Teammate 2** | Cancellation agent helper | Separate agent/flow, can share `sabre.py` and `vocalbridge.py` |

### Pluggable Design Principles:
- `agent.py` accepts preferences as a **dict argument** — doesn't care if it came from JSON, CSV, or a database
- `sabre.py` is a **shared utility** — any agent (booking or cancellation) can import and call its functions
- `vocalbridge.py` is a **shared utility** — handles voice for any agent flow
- `main.py` routes to the right agent based on context (booking vs cancellation)
- Preferences loader is a **thin adapter** — currently reads JSON, teammate will swap to CSV reader

---

## System Prompt (for Claude)

```
You are Tailwind, a friendly and efficient voice travel assistant. You help travelers plan and book complete trips through natural conversation.

TRAVELER PREFERENCES (use these proactively):
{preferences_json}

PERSONALITY:
- Warm, concise, conversational (you're speaking out loud)
- Naturally mention when you're using their preferences
- Keep responses to 2-3 sentences max (this is voice, not text)
- Confirm details before booking
- Suggest options based on their preferences first

RULES:
- Always use the traveler's home airport as origin unless they specify otherwise
- Prioritize their preferred airlines and hotel chains in results
- Respect budget constraints
- Never book without explicit confirmation
- When presenting options, lead with their preferred choices
- Use update_display tool to show cards on their screen as you find options

FLOW:
1. Greet by name, acknowledge loaded preferences
2. Ask where they're going (they may already say it)
3. Search flights → present top 3 → let them pick
4. Ask about hotels → search → present options → let them pick
5. Show trip summary → get confirmation → book
6. Provide confirmation numbers
```

---

## Hackathon Credentials Setup

| Service | How to Get |
|---------|-----------|
| **Sabre** | Sign up at developer.sabre.com with hackathon email → access hackathon-2026 collection → 7 days free |
| **Vocal Bridge** | Sign up at vocalbridgeai.com → Billing → Developer Plan → promo code `VBHACKMONTH` → 1 month free |
| **LandingAI** | Register at ade.landing.ai with hackathon email → 1000 credits (10,000 more on 7/16) |
| **PayPal** | Option 1: developer.paypal.com/dashboard OR Option 2: use pre-configured sandbox creds from organizers |

---

## Verification Checklist

- [ ] `./run.sh` starts without errors
- [ ] Landing page renders with premium dark+gold theme
- [ ] "Start Planning" connects WebRTC (or falls back gracefully)
- [ ] Speaking triggers agent response in transcript
- [ ] Flight search returns cards on right panel
- [ ] Clicking a card selects it (same as voice)
- [ ] Hotel search works after flight is selected
- [ ] Trip summary shows before booking
- [ ] "Confirm & Book" completes the flow
- [ ] Preferences are mentioned naturally by the agent
- [ ] DEMO_MODE works fully offline
- [ ] Outbound call mode still works
- [ ] "Start New Trip" resets everything

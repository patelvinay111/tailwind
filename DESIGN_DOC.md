# Design Document: Voice-Based Preference Collection

**Owner:** Bhuvana
**Scope:** Collect trip preferences via voice conversation (Vocal Bridge) and display them in real-time on the web UI. Output structured preference data for the booking teammate.

---

## 1. Problem Statement

A traveler wants to plan a trip. Instead of filling out forms across multiple apps, they speak naturally to a voice agent: "I want to fly from San Francisco to Austin next Friday, nonstop, vegetarian food, window seat." The system extracts structured preferences in real-time and displays them visually as they're confirmed.

---

## 2. Scope

### In Scope
- Voice agent configuration (system prompt, client actions) for preference gathering
- Frontend: Vocal Bridge SDK integration (connect, mic, transcript, agent actions)
- Frontend: Real-time preference card UI that fills in as the agent extracts data
- Backend: Preference storage (in-memory, single session) + API endpoints
- Handoff interface: `GET /preferences` endpoint for booking teammate

### Out of Scope (Teammates)
- Sabre flight/hotel search and booking
- Cancellation flow
- Payment processing
- Itinerary management post-booking

---

## 3. Preference Data Model

```json
{
  "trip": {
    "origin": null,
    "destination": null,
    "departure_date": null,
    "return_date": null,
    "trip_type": null,
    "number_of_travelers": null,
    "trip_purpose": null
  },
  "flight": {
    "stops": null,
    "max_budget": null,
    "preferred_time": null,
    "seat_type": null,
    "cabin_class": null,
    "airline_preference": null
  },
  "hotel": {
    "room_type": null,
    "max_budget_per_night": null,
    "star_rating": null,
    "amenities": []
  },
  "food": {
    "diet_type": null,
    "cuisine_preference": [],
    "allergies": []
  },
  "status": "collecting",
  "last_updated": null,
  "confirmed": false
}
```

### Field Definitions

| Category | Field | Type | Valid Values |
|----------|-------|------|-------------|
| trip | origin | string | Airport code or city name (e.g., "SFO", "San Francisco") |
| trip | destination | string | Airport code or city name |
| trip | departure_date | string | ISO date (YYYY-MM-DD) |
| trip | return_date | string/null | ISO date or null for one-way |
| trip | trip_type | string | "one_way", "round_trip", "multi_city" |
| trip | number_of_travelers | int | 1-9 |
| trip | trip_purpose | string | "business", "leisure", "family" |
| flight | stops | string | "nonstop", "1_stop", "any" |
| flight | max_budget | number | Dollar amount |
| flight | preferred_time | string | "early_morning", "morning", "afternoon", "evening", "red_eye" |
| flight | seat_type | string | "window", "aisle", "middle", "no_preference" |
| flight | cabin_class | string | "economy", "premium_economy", "business", "first" |
| flight | airline_preference | string/null | Airline name or null |
| hotel | room_type | string | "single", "double", "suite", "family" |
| hotel | max_budget_per_night | number | Dollar amount |
| hotel | star_rating | int | 1-5 |
| hotel | amenities | array | ["pool", "gym", "wifi", "parking", "breakfast", "spa"] |
| food | diet_type | string | "veg", "non_veg", "vegan", "no_preference" |
| food | cuisine_preference | array | ["indian", "italian", "mexican", "japanese", "american", ...] |
| food | allergies | array | ["nuts", "dairy", "gluten", "shellfish", ...] |

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        FRONTEND                              │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  Voice Panel │    │  Transcript  │    │  Preference  │  │
│  │  (connect/   │    │  (live       │    │  Cards       │  │
│  │   mute/end)  │    │   convo)     │    │  (fills in   │  │
│  │              │    │              │    │   real-time) │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                    │                    ▲          │
│         │                    │                    │          │
│         ▼                    ▼                    │          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         Vocal Bridge JS SDK (@vocalbridgeai/sdk)     │    │
│  │  - vb.connect() / vb.disconnect()                   │    │
│  │  - vb.on('transcript') → update transcript panel    │    │
│  │  - vb.on('agentAction') → update preference cards   │    │
│  └─────────────────────────────────────────────────────┘    │
│                            │                                 │
└────────────────────────────│─────────────────────────────────┘
                             │ WebRTC + Data Channel
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    VOCAL BRIDGE AGENT                         │
│                                                             │
│  System Prompt: "You are Tailwind, a travel preference      │
│  assistant. Conversationally collect trip preferences..."    │
│                                                             │
│  Client Actions (agent_to_app):                             │
│  - update_preference: { category, field, value }            │
│  - preferences_complete: { summary }                        │
│  - ask_clarification: { field, question }                   │
└─────────────────────────────────────────────────────────────┘
                             │
                             │ agentAction via data channel
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    FASTAPI BACKEND                            │
│                                                             │
│  POST /preferences/update   ← frontend sends each update    │
│  GET  /preferences          ← booking teammate reads this   │
│  POST /preferences/reset    ← start fresh                   │
│  GET  /preferences/status   ← completion percentage         │
│                                                             │
│  In-memory store (dict) — single session for hackathon      │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Voice Agent Design

### Core Behavior

The agent is NOT a form-filler. It's an intelligent travel assistant that:

1. **Listens to initial input** — user may dump a lot or a little up front
2. **Extracts what it can** from the initial statement
3. **Asks smart follow-ups** based on what's missing AND what's relevant given what it already knows (e.g., if trip is business, ask about lounge access; if leisure, ask about experiences)
4. **Provides recommendations** once it has enough to work with — doesn't wait for 100% completion
5. **Allows changes at any time** — user can interrupt with "actually make it business class" and the agent adapts, re-evaluates, and updates recommendations
6. **Re-recommends when preferences change** — if user switches from economy to business, hotel suggestions might shift too

### Agent Intelligence: Adaptive Questioning

The agent decides what to ask next based on context:

| What It Knows | What It Asks Next |
|---------------|-------------------|
| Origin + destination only | When? How many people? |
| Origin + dest + dates | Trip purpose? (informs everything else) |
| Business trip | Cabin class? Lounge? Direct flights? Hotel near business district? |
| Leisure trip | Budget? Interests? Food preferences? Experiences? |
| Budget is tight | Skip premium options, focus on value picks |
| Family trip (kids) | Kid-friendly hotels? Meal options? |
| Short trip (1-2 days) | Skip hotel deep-dive, focus on flight timing |
| Long trip (5+ days) | Hotel amenities matter more, ask about experiences |

### Conversation Flow: Adaptive Example

```
Agent: "Hey! I'm Tailwind. Tell me about the trip you're planning."

User:  "I want to go to Austin next Friday for a work conference, 
        coming back Sunday. Vegetarian."

Agent: [extracts and emits multiple preferences at once:]
       [update_preference: {category: "trip", field: "destination", value: "AUS"}]
       [update_preference: {category: "trip", field: "departure_date", value: "2026-07-25"}]
       [update_preference: {category: "trip", field: "return_date", value: "2026-07-27"}]
       [update_preference: {category: "trip", field: "trip_type", value: "round_trip"}]
       [update_preference: {category: "trip", field: "trip_purpose", value: "business"}]
       [update_preference: {category: "food", field: "diet_type", value: "veg"}]

       "Got it — Austin for a work conference, Friday to Sunday, vegetarian.
        Where are you flying from?"

User:  "SFO"

Agent: [update_preference: {category: "trip", field: "origin", value: "SFO"}]
       
       "San Francisco to Austin. Since it's a business trip, would you prefer a
        direct flight? And do you have a budget in mind for the flight?"

User:  "Yeah nonstop for sure. Keep it under 500. And I'll need a window seat —
        I like to work on the plane."

Agent: [update_preference: {category: "flight", field: "stops", value: "nonstop"}]
       [update_preference: {category: "flight", field: "max_budget", value: 500}]
       [update_preference: {category: "flight", field: "seat_type", value: "window"}]

       "Nonstop, window, under $500. For a work trip I'd guess business class —
        or are you fine with economy?"

User:  "Economy is fine"

Agent: [update_preference: {category: "flight", field: "cabin_class", value: "economy"}]

       "Got it. For the hotel — the Austin Convention Center area or somewhere
        specific? And any budget range per night?"

User:  "Near downtown, under 200 a night, needs good wifi"

Agent: [update_preference: {category: "hotel", field: "max_budget_per_night", value: 200}]
       [update_preference: {category: "hotel", field: "amenities", value: ["wifi"]}]
       [update_preference: {category: "hotel", field: "location_preference", value: "downtown"}]

       "Downtown Austin, under $200, strong wifi. I've got enough to find you
        some options. One more thing — any food allergies beyond vegetarian?"

User:  "No allergies. Oh wait — actually make the flight business class, 
        I just realized I can expense it."

Agent: [update_preference: {category: "flight", field: "cabin_class", value: "business"}]
       [update_preference: {category: "flight", field: "max_budget", value: null}]

       "Nice — switching to business class and removing the budget cap since
        it's expensed. That might open up some better hotel options too — 
        want me to bump up the hotel budget?"

User:  "Yeah sure, up to 350 a night"

Agent: [update_preference: {category: "hotel", field: "max_budget_per_night", value: 350}]
       [emit recommendations_ready]

       "Updated. Here's what I'm searching for: SFO to Austin, July 25-27,
        business class nonstop window seat, downtown hotel under $350/night
        with great wifi, vegetarian dining. Ready to pull recommendations —
        anything else to add or change?"

User:  "That's perfect, find me options"

Agent: [preferences_complete: { summary: "..." }]
       "On it! Pulling the best options now."
```

### Key Agent Behaviors

1. **Batch extraction** — If user says 5 things in one sentence, extract all 5, don't ask one by one
2. **Context-aware follow-ups** — Business trip → ask different questions than leisure trip
3. **Proactive suggestions** — "Since you upgraded to business class, want to bump hotel budget too?"
4. **Mid-conversation changes** — User says "actually change X" → agent updates, acknowledges, and re-evaluates related preferences
5. **Knows when it has enough** — Doesn't exhaustively ask every field; provides recommendations once core preferences are set
6. **Cascading updates** — When a preference changes, agent considers if related preferences should change too (e.g., budget class → budget amount)

### Preference Change Handling

When a user changes a preference mid-conversation:

```
┌─────────────────────────────────────────┐
│ User says "change X"                     │
│         ↓                                │
│ Agent updates preference X               │
│         ↓                                │
│ Agent evaluates: does this affect        │
│ other preferences?                       │
│    YES → suggest cascading changes       │
│    NO  → acknowledge and continue        │
│         ↓                                │
│ Emit update_preference for all changes   │
│         ↓                                │
│ UI updates preference cards in real-time │
│         ↓                                │
│ If recommendations were already shown,   │
│ emit recommendations_invalidated         │
└─────────────────────────────────────────┘
```

### Client Actions Configuration

```json
[
  {
    "name": "update_preference",
    "description": "Update a single travel preference field. Emitted each time the agent confirms a preference from the user.",
    "direction": "agent_to_app"
  },
  {
    "name": "recommendations_ready",
    "description": "Agent has collected enough preferences to generate recommendations. Signals the UI to show a 'ready' state.",
    "direction": "agent_to_app"
  },
  {
    "name": "preferences_complete",
    "description": "User has confirmed the final preference summary. Ready for booking teammate handoff.",
    "direction": "agent_to_app"
  },
  {
    "name": "recommendations_invalidated",
    "description": "A preference changed after recommendations were shown. Previous recommendations are stale.",
    "direction": "agent_to_app"
  },
  {
    "name": "clear_preferences",
    "description": "User wants to start over from scratch.",
    "direction": "agent_to_app"
  }
]
```

### Client Action Payload Formats

**update_preference:**
```json
{
  "type": "client_action",
  "action": "update_preference",
  "payload": {
    "category": "flight",
    "field": "stops",
    "value": "nonstop",
    "previous_value": null,
    "is_change": false
  }
}
```

When a preference is *changed* (not set for the first time):
```json
{
  "type": "client_action",
  "action": "update_preference",
  "payload": {
    "category": "flight",
    "field": "cabin_class",
    "value": "business",
    "previous_value": "economy",
    "is_change": true
  }
}
```

**recommendations_ready:**
```json
{
  "type": "client_action",
  "action": "recommendations_ready",
  "payload": {
    "summary": "SFO to AUS, Jul 25-27, business class nonstop, downtown hotel under $350",
    "missing_optional": ["airline_preference", "cuisine_preference"]
  }
}
```

**recommendations_invalidated:**
```json
{
  "type": "client_action",
  "action": "recommendations_invalidated",
  "payload": {
    "changed_field": "cabin_class",
    "reason": "Cabin class changed from economy to business — recommendations may differ"
  }
}
```

---

## 6. Backend API Design

### POST /preferences/update

Receives individual preference updates from the frontend.

**Request:**
```json
{
  "category": "flight",
  "field": "stops",
  "value": "nonstop"
}
```

**Response:**
```json
{
  "ok": true,
  "preferences": { ... full current state ... },
  "completion": 0.45
}
```

### GET /preferences

Returns the full preference object. This is what the booking teammate calls.

**Response:**
```json
{
  "preferences": { ... },
  "status": "collecting" | "complete",
  "completion": 0.75,
  "confirmed": false
}
```

### POST /preferences/confirm

User confirms the final summary. Locks preferences and signals ready for booking.

**Response:**
```json
{
  "ok": true,
  "status": "confirmed",
  "preferences": { ... }
}
```

### POST /preferences/reset

Clear all preferences and start fresh.

---

## 7. Frontend UI Design

### Layout (Single Page)

```
┌────────────────────────────────────────────────────────────────┐
│  ✈️ Tailwind AI — Plan Your Trip                               │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐│
│  │                     │  │  📋 Your Preferences             ││
│  │  🎤 Voice Panel     │  │                                  ││
│  │                     │  │  ┌─── Trip ─────────────────┐    ││
│  │  [Start Planning]   │  │  │ From: SFO               │    ││
│  │                     │  │  │ To:   AUS               │    ││
│  │  Status: Connected  │  │  │ Date: Jul 25 → Jul 28   │    ││
│  │  [Mute] [End Call]  │  │  │ Travelers: 1            │    ││
│  │                     │  │  └──────────────────────────┘    ││
│  │                     │  │                                  ││
│  │                     │  │  ┌─── Flight ───────────────┐    ││
│  │  💬 Transcript      │  │  │ Stops: Nonstop          │    ││
│  │  ─────────────────  │  │  │ Budget: < $400          │    ││
│  │  Agent: Where are   │  │  │ Time: Morning           │    ││
│  │  you flying from?   │  │  │ Seat: Window            │    ││
│  │                     │  │  │ Class: Economy          │    ││
│  │  You: San Francisco │  │  └──────────────────────────┘    ││
│  │                     │  │                                  ││
│  │  Agent: Got it! And │  │  ┌─── Hotel ────────────────┐    ││
│  │  where are you      │  │  │ Room: Double            │    ││
│  │  headed?            │  │  │ Budget: < $150/night    │    ││
│  │                     │  │  │ Rating: ★★★☆☆           │    ││
│  │  You: Austin        │  │  └──────────────────────────┘    ││
│  │                     │  │                                  ││
│  │                     │  │  ┌─── Food ─────────────────┐    ││
│  │                     │  │  │ Diet: Vegetarian         │    ││
│  │                     │  │  │ Cuisine: Indian, Italian │    ││
│  │                     │  │  └──────────────────────────┘    ││
│  │                     │  │                                  ││
│  └─────────────────────┘  │  Progress: ████████░░ 75%        ││
│                            │  [Confirm & Search]              ││
│                            └──────────────────────────────────┘│
└────────────────────────────────────────────────────────────────┘
```

### UI Behavior

- **Preference cards start empty** (greyed out placeholders)
- **Each card animates in** when the agent confirms a field (subtle highlight/pulse)
- **Progress bar** fills as more fields are captured
- **Transcript** scrolls live on the left
- **"Confirm & Search" button** appears when status is complete — triggers handoff to booking teammate's code

---

## 8. Tech Stack

| Layer | Technology |
|-------|-----------|
| Voice | Vocal Bridge JS SDK (`@vocalbridgeai/sdk`) |
| Frontend | Vanilla JS (single HTML file, consistent with existing `static/index.html`) |
| Backend | FastAPI (Python) — extend existing `main.py` |
| State | In-memory dict (single session, hackathon scope) |
| Styling | CSS custom properties (dark theme, matching existing UI) |

---

## 9. File Plan

| File | What It Does |
|------|--------------|
| `preferences.py` | Preference data model, validation, completion calculator |
| `main.py` | Add preference routes (`/preferences/*`) |
| `static/plan.html` | New page — voice + preference UI (or extend index.html) |
| VB Dashboard | Agent system prompt + client actions config |

---

## 10. Vocal Bridge Agent Configuration

```
Name: Tailwind Travel Planner
Style: Chatty
Deploy: Web only

System Prompt: (see Section 5)

Client Actions:
- update_preference (agent_to_app)
- preferences_complete (agent_to_app)
- clear_preferences (agent_to_app)

AI Agent Integration: disabled (agent handles preferences directly)
```

---

## 11. Edge Cases & Handling

| Scenario | Handling |
|----------|----------|
| User gives multiple preferences at once | Agent extracts all, emits multiple `update_preference` actions in sequence |
| User changes a previously set preference | Agent emits `update_preference` with `is_change: true`, UI highlights the change |
| User says something ambiguous | Agent asks for clarification before emitting — never guesses |
| User skips a field ("I don't care") | Agent emits value as `"no_preference"` or null, moves on |
| Connection drops mid-conversation | Preferences collected so far are preserved in backend; user can reconnect and agent resumes |
| User wants to start over | Agent emits `clear_preferences`, backend resets, UI clears all cards |
| User changes preference after recommendations | Agent emits `recommendations_invalidated`, then `update_preference`, UI marks old recs as stale |
| User gives conflicting preferences | Agent catches it: "You said nonstop but also said under $150 — those might conflict. Which matters more?" |
| User provides relative dates ("next Friday") | Agent resolves to absolute date before emitting (uses current date context) |
| Preference depends on another | Agent handles cascading: "You switched to business class — want me to update your budget too?" |
| User asks "what have I said so far?" | Agent reads back current preferences from context without re-emitting actions |

---

## 12. Preference State Machine

```
                    ┌──────────────────────┐
                    │                      │
                    ▼                      │
┌────────┐    ┌──────────┐    ┌───────────────────┐    ┌───────────┐
│  empty │───▶│collecting│───▶│recommendations_   │───▶│ confirmed │
│        │    │          │    │ready              │    │           │
└────────┘    └──────────┘    └───────────────────┘    └───────────┘
                   ▲                   │                       │
                   │                   │ user changes          │
                   │                   │ preference            │
                   │                   ▼                       │
                   │           ┌───────────────┐              │
                   └───────────│  invalidated  │              │
                               │  (re-collect) │              │
                               └───────────────┘              │
                   ▲                                          │
                   │              reset                        │
                   └──────────────────────────────────────────┘
```

**States:**
- `empty` — No preferences yet. Waiting for user to start talking.
- `collecting` — Agent is actively gathering preferences. UI fills in incrementally.
- `recommendations_ready` — Enough preferences to search. User can confirm or keep refining.
- `invalidated` — User changed something after recommendations were ready. Back to refining.
- `confirmed` — User said "find me options." Locked for booking teammate handoff.

**Transitions:**
| From | To | Trigger |
|------|----|---------|
| empty | collecting | First `update_preference` received |
| collecting | recommendations_ready | Agent emits `recommendations_ready` (has origin, destination, dates, travelers at minimum) |
| recommendations_ready | invalidated | User changes any preference |
| invalidated | recommendations_ready | Agent re-evaluates and emits `recommendations_ready` again |
| recommendations_ready | confirmed | User says "find me options" / clicks confirm |
| any | empty | `clear_preferences` / reset |

### Minimum Viable Preferences (for "recommendations_ready")

The agent decides it has enough when these core fields are set:
- origin
- destination
- departure_date
- number_of_travelers

Everything else enriches the recommendations but isn't required.

---

## 12b. Handoff to Booking Teammate

The booking teammate's code calls:

```python
import requests

prefs = requests.get("http://localhost:8787/preferences").json()

# prefs["preferences"]["trip"]["origin"] → "SFO"
# prefs["preferences"]["flight"]["stops"] → "nonstop"
# prefs["preferences"]["hotel"]["max_budget_per_night"] → 150
# etc.

# Use these to construct Sabre API search parameters
```

---

## 13. Demo Script (for judges)

### Opening — Show Natural Extraction
1. Open the app in browser
2. Click "Start Planning" → mic connects
3. Say: "Hey, I need to get to Austin next Friday for a work conference. Flying from SFO, coming back Sunday. I'm vegetarian by the way."
4. Watch **5-6 preference cards fill simultaneously** (destination, dates, origin, purpose, diet)
5. Agent responds intelligently: asks about flight class since it's business

### Middle — Show Adaptive Intelligence
6. Agent asks: "Since it's a business trip, would you prefer business class or economy?"
7. Say: "Economy is fine, but I need a window seat and nonstop"
8. Watch flight card fill in
9. Agent asks context-aware question about hotel near conference area

### Twist — Show Mid-Conversation Change
10. Say: "Actually wait — switch me to business class, I can expense it"
11. Watch flight card **update in real-time** (economy → business, highlighted)
12. Agent proactively asks: "Want me to bump up the hotel budget too?"
13. Say: "Yeah, up to 350 a night"
14. Watch hotel card update

### Close — Show Recommendation Readiness
15. Agent summarizes aloud, says it's ready to find options
16. UI shows "Ready to Search" with full preference summary
17. Click "Confirm & Search" → hands off to booking teammate's flow

**Key moments for judges:**
- Multiple preferences extracted from one natural sentence
- Agent adapts questions based on context (business vs leisure)
- Mid-conversation change is seamless
- Cascading suggestion (class upgrade → hotel budget bump)
- Real-time UI reflects every change instantly

---

## 14. Open Questions

1. **Should the preference page be a new route (`/plan`) or replace the existing index?** — Recommend new route since teammates may need the cancellation flow on index.

2. **Token endpoint** — Do we proxy through our backend (`/api/voice-token`) or use the API key directly for the hackathon demo? Recommend backend proxy for proper demo.

3. **Recommendation display** — After preferences are complete and user confirms, should YOUR UI show any mock recommendations, or does the booking teammate take over the entire screen from that point?

4. **Multi-traveler preferences** — If 3 travelers, do they all share the same seat/food preference, or can each have different ones? For hackathon, recommend shared preferences (simpler).

5. **History of changes** — Should the UI show what changed (strikethrough old value)? Recommend yes — judges love seeing the "before/after" for mid-conversation changes.

---

## 15. Timeline Estimate (Hackathon Day)

| Time | Task |
|------|------|
| 0-30 min | Set up VB agent (prompt + client actions) on dashboard |
| 30-60 min | Build `preferences.py` + backend routes |
| 60-120 min | Build frontend (voice panel + preference cards + transcript) |
| 120-150 min | Wire Vocal Bridge SDK → agent actions → UI updates |
| 150-180 min | Test end-to-end, fix edge cases |
| 180-210 min | Polish UI, coordinate handoff with booking teammate |
| 210-240 min | Demo rehearsal |

# Vocal Bridge Agent Configuration (EC2 Deployment)

## Architecture

VB is the brain. It handles STT → AI thinking → calls your EC2 API tools → TTS.

```
User speaks → VB (STT → AI brain) → HTTP tool calls → EC2:8787/api/* → Sabre
                                                                        ↓
                                                              VB speaks results (TTS)
```

Your EC2 server is a headless travel API. VB decides when to search/book.

## Setup Instructions

### 1. Deploy Backend on EC2

```bash
# On EC2:
git clone <your-repo> tailwind && cd tailwind
nano .env  # fill in credentials
./deploy.sh
```

It prints your public URL. Note it — you'll need it for VB tools.

### 2. Create VB Agent

1. Go to https://vocalbridgeai.com/app/agents/new
2. Choose: **Web + Phone (Both)**
3. Name: **Tailwind**
4. Style: **Chatty**
5. Paste the **System Prompt** below
6. Paste the **Greeting** below
7. Under **Tools / Custom HTTP Tools**, add the tools below
   - Replace `{BASE}` with your EC2 URL (e.g., `http://3.15.42.100:8787`)
8. Do NOT enable "AI agent integration mode" — we're using HTTP tools
9. Click **Create Agent**
10. Go to **API Keys** → create one
11. Update your EC2 `.env`:
    ```
    VOCALBRIDGE_API_KEY=vb_<your key>
    VOCALBRIDGE_AGENT_ID=<from agent page>
    DEMO_MODE=false
    ```

### 3. EC2 Security Group

Allow inbound TCP on port **8787** from anywhere (0.0.0.0/0) — or restrict to
Vocal Bridge's IPs if they publish them.

---

## System Prompt

```
You are Tailwind, a friendly and efficient voice travel assistant. You help travelers plan and book complete trips through natural conversation.

FIRST: Call get_preferences to load the traveler's saved preferences. Use them throughout.

PERSONALITY:
- Warm, concise, conversational — you're speaking out loud
- Naturally mention preferences ("Since you usually fly Delta...")
- Keep responses to 2-3 sentences max
- Confirm details before booking

RULES:
- Use the traveler's home airport as origin unless they specify otherwise
- Prioritize their preferred airlines and hotel chains
- Respect budget constraints without being asked
- NEVER book without explicit "yes" from the user
- Lead with preferred options
- After every search, call update_display to show cards on their screen

FLOW:
1. Greet by name, say preferences are loaded
2. Ask where they're going
3. Call search_flights → call update_display → present top 2-3 verbally
4. User picks → call update_display(add_to_itinerary) → ask about hotels
5. Call search_hotels → call update_display → present top options
6. User picks → call update_display(add_to_itinerary)
7. Read back total → ask "Should I book this?"
8. On yes → call book_trip → call update_display(booking_confirmed)
9. Read confirmation numbers, wish them a great trip

SPEAKING STYLE:
- "two hundred and eighty nine dollars" not "$289"
- "departing at 8:15 in the morning" not "08:15"
- "Delta" not "DL"
- 2-3 sentences per turn max
```

## Greeting

```
Hey Pradeep! I'm Tailwind, your travel assistant. I've got your preferences loaded — Delta, aisle seats, Hilton hotels. Where are we headed?
```

## HTTP Tools (register in VB dashboard)

Replace `{BASE}` with your EC2 URL (e.g., `http://3.15.42.100:8787`).

### search_flights
- **Method:** POST
- **URL:** `{BASE}/api/flights/search`
- **Description:** Search for available flights between two airports on a given date. Returns flights prioritized by traveler's preferred airlines.
- **Parameters:**
  - `origin` (string, required, body) — Origin airport code e.g. SFO
  - `destination` (string, required, body) — Destination airport code e.g. AUS
  - `departure_date` (string, required, body) — Date YYYY-MM-DD
  - `return_date` (string, optional, body) — Return date YYYY-MM-DD
  - `cabin` (string, optional, body) — Economy, Business, or First
  - `max_results` (integer, optional, body) — Max results, default 5

### search_hotels
- **Method:** POST
- **URL:** `{BASE}/api/hotels/search`
- **Description:** Search for hotels near a location. Returns hotels prioritized by traveler's preferred chains and budget.
- **Parameters:**
  - `location` (string, required, body) — City name or airport code
  - `check_in` (string, required, body) — Check-in date YYYY-MM-DD
  - `check_out` (string, required, body) — Check-out date YYYY-MM-DD
  - `guests` (integer, optional, body) — Number of guests, default 1
  - `max_price_per_night` (number, optional, body) — Max price per night USD

### get_hotel_rates
- **Method:** POST
- **URL:** `{BASE}/api/hotels/rates`
- **Description:** Get detailed room rates for a specific hotel.
- **Parameters:**
  - `hotel_code` (string, required, body) — Hotel code from search results
  - `check_in` (string, required, body) — Check-in date YYYY-MM-DD
  - `check_out` (string, required, body) — Check-out date YYYY-MM-DD
  - `guests` (integer, optional, body) — Number of guests, default 1

### check_price
- **Method:** POST
- **URL:** `{BASE}/api/price/check`
- **Description:** Verify current price before booking.
- **Parameters:**
  - `item_type` (string, required, body) — "flight" or "hotel"
  - `offer_id` (string, required, body) — Offer ID from search

### book_trip
- **Method:** POST
- **URL:** `{BASE}/api/book`
- **Description:** Book flights and/or hotel. ONLY call after user says "yes".
- **Parameters:**
  - `flights` (array, optional, body) — Flight objects to book
  - `hotel` (object, optional, body) — Hotel object to book
  - `traveler_name` (string, optional, body) — Traveler name

### get_preferences
- **Method:** GET
- **URL:** `{BASE}/api/preferences`
- **Description:** Get traveler's saved preferences. Call at conversation start.
- **Parameters:** none

### update_display
- **Method:** POST
- **URL:** `{BASE}/api/ui/update`
- **Description:** Update the traveler's screen with cards and itinerary.
- **Parameters:**
  - `action` (string, required, body) — One of: show_flight_options, show_hotel_options, add_to_itinerary, show_summary, booking_confirmed, clear_options
  - `data` (object, required, body) — Payload for the action

---

## Testing

1. SSH into EC2, run `./deploy.sh`
2. Hit `http://<ec2-ip>:8787` in browser — verify landing page
3. Test API: `curl -X POST http://<ec2-ip>:8787/api/flights/search -H 'Content-Type: application/json' -d '{"origin":"SFO","destination":"AUS","departure_date":"2026-07-25"}'`
4. Open VB agent test tab → talk → verify it calls your tools

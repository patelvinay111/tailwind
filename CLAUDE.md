# Hackathon: Voice AI Travel Agent — "Tailwind AI"

## Project Goal

Build a voice-powered AI travel agent that unifies flights, hotels, ground transport, dining, and experiences into a single spoken conversation. The agent should book and manage a complete trip itinerary by voice — not a chatbot, not a notification, but a real voice agent.

**Required integrations:** Sabre Agentic APIs (travel) + Vocal Bridge (voice AI layer)

---

## Current Implementation

The app already implements a **proactive flight-disruption rebooking flow**:

1. Flight gets cancelled → agent calls the traveler (Vocal Bridge outbound)
2. Traveler says "yes" → Sabre search for alternatives → Claude picks the best one → Sabre books it
3. Web UI shows old vs. new itinerary cards in real-time

**State machine:** `idle → calling → awaiting_confirmation → rebooking → done` (or `declined` / `error`)

### Files
| File | Role |
|------|------|
| `main.py` | FastAPI app: routes, in-memory state, orchestration |
| `agent.py` | Claude brain: opening line, intent detection, flight selection |
| `sabre.py` | Sabre OAuth2 auth + flight search (BFM v4) + booking (Create PNR) |
| `vocalbridge.py` | Outbound call trigger + webhook normalization |
| `static/index.html` | Single-page UI (vanilla JS, polls `/status`) |
| `run.sh` | One-command setup (Python 3.13, venv, deps, server) |

### Running
```bash
./run.sh                    # setup + start on port 8787
# Open http://localhost:8787, click "Simulate Flight Cancellation"
# Then simulate traveler saying yes:
curl -X POST http://localhost:8787/vocalbridge/webhook \
  -H 'Content-Type: application/json' \
  -d '{"event":"transcript","speaker":"user","text":"yes book the next one"}'
```

### Going Live (on-site)
Set `DEMO_MODE=false` in `.env` and fill in credentials. Each `TODO(on-site)` in the code marks where to reconcile with hackathon docs.

---

## Architecture Overview

```
User (voice) <-> Vocal Bridge (WebRTC/outbound call) <-> Our AI Agent (Claude) <-> Sabre APIs (travel data/booking)
                                                              ↕
                                                     FastAPI backend (main.py)
                                                              ↕
                                                     Web UI (static/index.html)
```

The voice agent handles natural conversation flow. When the user asks about flights, hotels, etc., our agent delegates to Sabre's travel APIs, then speaks the results back conversationally.

---

## Sabre Agentic APIs (Travel)

Sabre's Agentic-ready APIs are battle-tested travel technology APIs adapted for LLM-based applications.

### Base URL
```
https://developer.sabre.com/product-collection/agentic-api/1.0
```

### Capabilities
- **Flight Search & Booking** — search, price, and book air itineraries
- **Hotel Search & Booking** — availability, rates, and reservations
- **Ground Transport** — car rentals and transfers
- **Trip Management** — retrieve, modify, and cancel bookings

### Authentication (OAuth2 Client Credentials)

**Token endpoint:** `POST {SABRE_BASE_URL}/v2/auth/token`

```python
# Already implemented in sabre.py
creds = f"{SABRE_CLIENT_ID}:{SABRE_CLIENT_SECRET}".encode()
basic = base64.b64encode(creds).decode()

resp = httpx.post(
    f"{SABRE_BASE_URL}/v2/auth/token",
    headers={
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    },
    data={"grant_type": "client_credentials"},
)
token = resp.json()["access_token"]
# Use as: Authorization: Bearer {token}
```

Alternatively, if the hackathon provides a pre-minted token, set `SABRE_ACCESS_TOKEN` directly.

### Key Patterns for AI Agents
- APIs are designed to be called by LLM tool-use / function-calling
- Responses are structured JSON suitable for agent parsing
- Stateless request/response — no session management needed
- Each API call is self-contained with all context in the request

### Environment Variables
```bash
SABRE_BASE_URL=https://api.cert.platform.sabre.com   # CERT (test) environment
SABRE_CLIENT_ID=<from hackathon>
SABRE_CLIENT_SECRET=<from hackathon>
SABRE_ACCESS_TOKEN=<optional: pre-minted bearer token>
SABRE_PCC=<pseudo city code, for booking>
```

### Already-Implemented Endpoints (in sabre.py)
- **Search:** `POST /v4/offers/shop` (Bargain Finder Max v4)
- **Book:** `POST /v2/passenger/records` (Create Passenger Name Record)

### New Agentic API Endpoints (documented below)
- `POST v1/offers/flightShopLite` — lightweight cache-based search
- `POST v1/offers/flightShop` — full multi-source search
- `POST v1/offers/flightSearch` — inspirational/open-date search
- `POST v1/offers/flightRefresh` — bulk itinerary validation
- `POST v1/offers/flightCheck` — revalidate before booking
- Booking Management API — unified Create/Get/Modify/Cancel/Fulfill/Void/Refund
- Hotel Search/Rates/Price Check

### API Endpoints

#### Hotel Price Check
Confirms the rate for a specific room and rate option with the supplier before booking.

**Use case:** Validate that the price hasn't changed before committing to a booking.

**Auth:** Bearer token via OAuth Token Create REST API

**Request:**
```json
{
  "hotelPriceCheckRq": {
    "rateInfoRef": {
      "rateKey": "NFZ6Y/BZlGHH9RhcPEBtCN6zQT"
    }
  }
}
```

**Required fields:**
- `rateKey` — identifies the specific room and rate option (obtained from a prior hotel search/availability call)

**Flow:**
1. Send request with the `rateKey` from a previous availability response
2. API confirms the rate with the supplier in real-time
3. Returns the confirmed (possibly updated) price

#### Hotel Rates
Returns all available rates and inventory for a specific hotel property based on stay parameters.

**Use case:** Get all room rates for a specific hotel before selecting one to book.

**Auth:** Bearer token via OAuth Token Create REST API

**Request:**
```json
{
  "checkInDate": "2025-10-21",
  "checkOutDate": "2025-10-23",
  "hotelCode": "123456789",
  "numberOfAdults": 2,
  "numberOfChildren": 0
}
```

**Required fields:**
- `hotelCode` — the specific property identifier
- `checkInDate` — desired check-in (YYYY-MM-DD)
- `checkOutDate` — desired check-out (YYYY-MM-DD)
- `numberOfAdults` — guest count
- `numberOfChildren` — child guest count

**Flow:**
1. Send request with hotel code and stay dates
2. API fetches all available rates from the supplier
3. Returns comprehensive rate/room options (each with a `rateKey` for price check/booking)

#### Hotel Search
Broad availability search for hotel properties within a geographic area and radius.

**Use case:** Find available hotels near a location, airport, or address.

**Auth:** Bearer token via OAuth Token Create REST API

**Search methods (provide one):**
- `latitude` + `longitude` — geographic coordinates
- `referencePoint` — airport code (e.g., "DFW")
- `address` — street address

**Request:**
```json
{
  "radiusInMiles": 200,
  "checkInDate": "2025-10-21",
  "checkOutDate": "2025-10-23",
  "numberOfAdults": 2,
  "latitude": 35.04022,
  "longitude": -106.60919
}
```

**Required fields:**
- One of: `latitude`+`longitude`, `referencePoint`, or `address`
- `radiusInMiles` — search radius
- `checkInDate` / `checkOutDate` — stay dates (YYYY-MM-DD)
- `numberOfAdults` — guest count

**Flow:**
1. Send request with location + stay parameters
2. API searches for matching properties in the radius
3. Returns available hotels with stay details (use `hotelCode` from results to get rates)

#### Booking Management (8 methods)

A unified API for managing Sabre reservations (PNRs and Orders). Handles flights, hotels, cars — all content types (ATPCO, NDC, CSL, LCC) through a single normalized interface. This is the core booking lifecycle API.

**Auth:** Bearer token (ATK) via Create Access Token API. Same token used for Sabre MCP Server.

**Methods:**

**1. Get Booking**
Retrieves a normalized view of a reservation combining PNR + Order data, plus ticketing, pricing, and fare rules.
- Input: `confirmationId` (PNR locator / Order ID)
- Returns: full booking details regardless of content source

**2. Create Booking**
Creates bookings for flights (ATPCO/NDC/LCC), hotels (CSL/legacy), and cars in a single call.
- Input: traveler info, flight/hotel/car segments
- Returns: normalized view of new booking with `confirmationId`
- Prerequisite: Store Passenger Type In PNR must be enabled in TJR

**3. Cancel Booking**
Cancels entire reservation or specific segments. Can void/refund flight tickets automatically.
- Input: `confirmationId` + optional segment selection + `flightTicketOperation` (VOID or REFUND)
- Supports: partial cancellation, error handling policy, LCC refunds

**4. Modify Booking**
Modifies existing bookings (hotel, group, ATPCO, NDC content).
- Input: `confirmationId` + `bookingSignature` (from Get Booking) + changes
- Prerequisite: call Get Booking first to get `bookingSignature`
- Supports: add/modify/delete operations in single call

**5. Fulfill Flight Tickets**
Issues electronic tickets and EMDs for ATPCO or NDC bookings.
- Input: `confirmationId` + fulfillment details
- Returns: normalized view of issued documents

**6. Check Flight Tickets**
Verifies if tickets can be voided or refunded.
- Input: document numbers (up to 12) or `confirmationId`
- Returns: voidability/refundability status and applicable amounts

**7. Void Flight Tickets**
Voids electronic tickets and EMDs (up to 12 per call).
- Input: document numbers + `confirmationId`
- Stateless — voids and updates reservation in one call

**8. Refund Flight Tickets**
Refunds electronic tickets (up to 12 per call) with optional refund qualifiers.
- Input: document numbers + `confirmationId` + refund qualifiers
- Stateless — refunds and updates reservation in one call

**Typical booking flow:**
```
Hotel Search → Hotel Rates → Hotel Price Check → Create Booking → Get Booking
                                                       ↓
                                              Fulfill Flight Tickets
                                                       ↓
                                         Check/Void/Refund (if needed)
                                                       ↓
                                              Modify or Cancel Booking
```

#### Flight Refresh
High-volume itinerary validation — checks schedule existence and seat availability for up to 100 cached itineraries in one request against Sabre inventory. Sub-second response time.

**Endpoint:** `POST v1/offers/flightRefresh/`

**Auth:** Bearer token via OAuth Token Create API

**Use cases:**
- Validate cached flight offers before displaying to travelers
- Confirm schedule still exists and seats are still available
- Update internal cache content at scale
- Reduce unnecessary live shopping calls

**Validation returns:**
- Schedule validation passed/failed
- Availability confirmed in requested booking class
- Availability confirmed in alternative booking class

**Request:**
```json
{
  "journeys": [
    {
      "departureLocation": { "cityCode": "DXB" },
      "arrivalLocation": { "cityCode": "LHR" },
      "departureDate": "2025-07-26"
    },
    {
      "departureLocation": { "cityCode": "LHR" },
      "arrivalLocation": { "cityCode": "DXB" },
      "departureDate": "2025-07-30"
    }
  ],
  "itineraries": [
    {
      "journeys": [
        {
          "flights": [
            {
              "departureAirportCode": "DXB",
              "departureDate": "2025-07-26",
              "departureTime": "06:30",
              "arrivalAirportCode": "AMM",
              "arrivalDate": "2025-07-26",
              "arrivalTime": "09:00",
              "marketingAirlineCode": "RJ",
              "marketingFlightNumber": 613,
              "segmentDetails": { "bookingClassCode": "M" }
            }
          ]
        }
      ]
    }
  ],
  "travelers": [{ "passengerTypeCode": "ADT" }],
  "processingOptions": {
    "pseudoCityCode": "ABC1",
    "configurationId": "abc12345"
  }
}
```

**Required fields:**
- `journeys` — origin/destination/date pairs
- `itineraries` — detailed flight segments with airline, times, booking class
- `travelers` — passenger type code (e.g., "ADT" for adult)
- `processingOptions.pseudoCityCode` — Sabre PCC

**Response:**
```json
{
  "timestamp": "2025-09-09T09:09:09Z",
  "itineraries": [
    {
      "requestedItineraryIndex": 0,
      "isItineraryValid": true,
      "bookingClassCodeValidation": "Matched"
    }
  ]
}
```

**Limits:** Up to 100 itineraries per request

#### Flight Shop Lite
Streamlined multi-source flight shopping — finds the best available fares from ATPCO, NDC, and Low Cost Carriers using pre-computed offers from Sabre's organic cache. Fast, lightweight, and unlimited searches (look-to-book free pricing).

**Endpoint:** `POST v1/offers/flightShopLite`

**Auth:** Bearer token via OAuth Token Create API

**Key capabilities:**
- Lowest fare discovery across all content sources (ATPCO, NDC, LCC)
- Time/carrier/route/cabin filtering
- Public, private, and negotiated fares
- Branded fares, baggage/carry-on allowance info
- Voluntary change and refundability info
- Configurable offer tiers (50, 100, 200 itineraries)
- One-way and round-trip support

**Request:**
```json
{
  "journeys": [
    {
      "departureLocation": { "airportCode": "LAX" },
      "arrivalLocation": { "airportCode": "DFW" },
      "departureDate": "2026-07-09"
    }
  ],
  "travelers": [{ "passengerTypeCode": "ADT" }],
  "processingOptions": {
    "limitNumberOfOffers": 1
  }
}
```

**Required fields:**
- `journeys` — origin/destination airports + departure dates
- `travelers` — passenger type codes (ADT, CHD, INF, etc.)

**Optional:**
- `processingOptions.limitNumberOfOffers` — cap results
- Carrier/cabin/time/connection filters

**Response structure:**
```json
{
  "flights": [{ "id", "departureAirportCode", "arrivalAirportCode", "departureDate", "departureTime", "arrivalDate", "arrivalTime", "marketingAirlineCode", "marketingFlightNumber", "durationInMinutes" }],
  "journeys": [{ "id", "flightRefs": ["flight-id"], "requestedJourneyIndex" }],
  "offers": [{
    "id", "source": { "provider", "distributionModel" },
    "totalPrice": { "amount": "122.99", "currencyCode": "USD" },
    "items": [{ "fares": [{ "fareTotal", "fareComponents": [{ "fareBasisCode", "segmentDetails": [{ "bookingClassCode", "cabinName" }] }] }] }],
    "paymentTimeLimit", "journeyRefs"
  }]
}
```

**Flow for voice agent:**
1. User says "Find me a flight from LA to Dallas next Friday"
2. Call Flight Shop Lite with origin/destination/date
3. Parse offers — present top options by price/time/airline
4. User selects → proceed to Create Booking

#### Flight Reshop
Searches for itinerary exchange/reissue offers for an existing ticket or order. Finds valid rebooking alternatives and calculates fare differences. REST replacement for legacy ExchangeShoppingRQ SOAP service.

**Auth:** Bearer token (ATK via Create Access Token API, or ATH via Create Session)

**Use cases:**
- User wants to change an existing flight ("Can I switch to an earlier flight?")
- Rebooking after cancellations or schedule changes
- Finding reissue options with fare difference calculation

**Currently supports:** ATPCO content (NDC exchange in development)

**How it works:**
1. Validates input and retrieves original itinerary data
2. Finds available flights based on original ticket's voluntary change restrictions
3. Calculates fare difference between original and new ticket
4. Returns structured list of new journey offers

**Returns:**
- New journey options
- Fare difference (original vs. new)
- Applicable restrictions from the original ticket

**Flow for voice agent:**
1. User says "I need to change my flight to an earlier one"
2. Get Booking to retrieve current `confirmationId` and ticket details
3. Call Flight Reshop with ticket/order info + desired new dates
4. Present options with price differences
5. User confirms → Modify Booking

#### Flight Check
Converts cached itineraries into bookable offers — a mandatory step before checkout. Fully live transaction that revalidates price and availability without holding inventory. Replaces both Revalidate Itinerary API and Offer Price API.

**Endpoint:** `POST v1/offers/flightCheck/`

**Auth:** Bearer token via OAuth Token Create API

**Use cases:**
- Validate a selected itinerary is still available and at what price before booking
- Get `offerItemID` needed for Create Booking
- Check baggage, refundability, and change policies for the offer

**Supports:**
- ATPCO (via payload) and NDC (via `offerItemID`)
- Cabin preferences, branded fares, account/corporate codes
- Offer attributes: baggage allowance, carbon emissions, refundability, changeability
- Alternative offers if original fare/booking class unavailable
- Marriage group indicators for connecting flights

**Request (ATPCO example):**
```json
{
  "journeys": [
    {
      "flights": [
        {
          "departureAirportCode": "DXB",
          "departureDate": "2026-07-26",
          "departureTime": "06:30",
          "arrivalAirportCode": "AMM",
          "arrivalDate": "2026-07-26",
          "arrivalTime": "09:00",
          "marketingAirlineCode": "RJ",
          "marketingFlightNumber": 613,
          "segmentDetails": { "bookingClassCode": "M" }
        }
      ]
    }
  ],
  "fare": {
    "currencyCode": "USD",
    "cabin": { "logic": "Jump Cabin", "name": "Economy" },
    "validatingAirlineCodes": ["RJ"]
  },
  "retailing": {
    "returnOfferAttributes": ["Baggage", "Carbon Emissions"],
    "filterByOfferAttributes": {
      "hasFreeBaggage": true,
      "hasFreeRefund": true,
      "isChangeAllowed": true
    },
    "returnAdditionalOffers": { "numberOfAdditionalOffers": 4 }
  },
  "travelers": [{ "passengerTypeCode": "ADT", "givenName": "John", "surname": "Smith" }],
  "processingOptions": { "pseudoCityCode": "PC18" }
}
```

**Response includes:**
- `offers[]` — full price breakdown, fare components, validating airline, payment time limit
- `offerValidationResults[]` — `bookingClassCodeValidation`: "Matched" or "Same cabin"
- `offerAttributes` — checked baggage, carry-on, refundability, change fees (before/after departure)
- `flights[]`, `journeys[]` — normalized flight/journey structure

**Typical flow:**
```
Flight Shop Lite → User selects offer → Flight Check (validate + get offerItemID) → Create Booking
```

#### Flight Shop (Full)
Modern multi-source shopping API — the full-featured version that replaces Bargain Finder Max. Aggregates content from ATPCO, NDC, LCC, third-party providers, and virtual interlining into a unified response. Live availability + pre-computed offers.

**Endpoint:** `POST v1/offers/flightShop/`

**Auth:** Bearer token via OAuth Token Create API

**Difference from Flight Shop Lite:**
- Full live shopping (not just cache) — more accurate, slightly slower
- Supports virtual interlining (combining multiple suppliers)
- More content sources and distribution models
- Use Flight Shop Lite for speed; Flight Shop for comprehensive results

**Request (same structure as Flight Shop Lite):**
```json
{
  "journeys": [
    {
      "departureLocation": { "airportCode": "LAX" },
      "arrivalLocation": { "airportCode": "DFW" },
      "departureDate": "2026-07-09"
    }
  ],
  "travelers": [{ "passengerTypeCode": "ADT" }],
  "processingOptions": { "limitNumberOfOffers": 1 }
}
```

**Response structure (same as Flight Shop Lite):**
```json
{
  "flights": [{ "id", "departureAirportCode", "arrivalAirportCode", "departureDate", "departureTime", "arrivalDate", "arrivalTime", "marketingAirlineCode", "marketingFlightNumber", "durationInMinutes" }],
  "journeys": [{ "id", "flightRefs", "requestedJourneyIndex" }],
  "offers": [{
    "id", "source": { "provider", "distributionModel" },
    "totalPrice": { "amount", "currencyCode" },
    "items": [{ "fares": [{ "fareTotal", "fareComponents" }] }],
    "paymentTimeLimit", "journeyRefs"
  }]
}
```

**Key capabilities:**
- Customizable search: time windows, include/exclude airlines, max stops, branded fares
- Public and private/negotiated fares
- Multi-source: EDIFACT, API/XML, Direct NDC
- Aggregator model support (virtual interlining)

#### Flight Search (Inspirational Shopping)
Exploratory/inspirational search across large date ranges and geographies. Find the cheapest flights to anywhere, for flexible dates and multiple lengths of stay. Cache-based, sub-second results — ideal for "where can I go?" scenarios.

**Endpoint:** `POST v1/offers/flightSearch/`

**Auth:** Bearer token via OAuth Token Create API

**Use cases:**
- "Where can I fly for under $500 in October?" (open destination)
- "When is the cheapest time to fly to Tokyo?" (open date)
- Calendar/map mode price displays
- Destination inspiration by theme (Beach, Adventure, etc.)

**Supports:**
- **Open Destination:** search from an origin to anywhere (airport, city, country, region, theme)
- **Open Origin:** search from anywhere to a destination
- **Open Date:** departure date range up to 330 days, multiple lengths of stay
- **Grouping:** results per day, date range, or month
- **Budget filter:** max total fare
- **Content:** public cache, private custom cache, 3rd party, NDC/LCC cache

**Request:**
```json
{
  "departureLocation": {
    "locationType": "Airport",
    "locationCode": "DXB"
  },
  "arrivalLocations": [
    { "locationFilter": "Exclude", "location": { "locationType": "Country", "locationCode": "FR" } },
    { "locationFilter": "Limit To", "location": { "locationType": "Theme", "locationCode": "Beach" } }
  ],
  "departureDateRange": {
    "fromDate": "2026-09-29",
    "toDate": "2026-12-31"
  },
  "lengthsOfStay": [1, 3, 5],
  "processingOptions": {
    "publicContentPointOfSaleCountry": "US",
    "returnLowestNonStopFare": false,
    "returnFullOffers": true,
    "returnMode": "Per Month",
    "budget": { "maximumTotalFareAmount": 500, "currencyCode": "USD" }
  },
  "sources": {
    "providers": ["Sabre"],
    "distributionModels": ["ATPCO"]
  }
}
```

**Key parameters:**
- `departureLocation` — origin (Airport or City)
- `arrivalLocations` — filter by country/region/theme, include or exclude
- `departureDateRange` — from/to dates
- `lengthsOfStay` — array of trip durations in days
- `processingOptions.returnMode` — "Per Day", "Per Month", or date range
- `processingOptions.budget` — max fare filter

**Response:** Same normalized structure (flights/journeys/offers) as other Flight APIs

**Flow for voice agent:**
1. User says "Where can I go for a beach vacation under $500 in October?"
2. Call Flight Search with theme=Beach, budget, date range
3. Present top destinations with prices
4. User picks destination → Flight Shop or Flight Shop Lite for specific offers

---

## Vocal Bridge (Voice AI Layer)

Vocal Bridge provides real-time voice AI agents over WebRTC with sub-second latency.

### Core Concept
1. Get an API key from the Vocal Bridge dashboard
2. Your backend exchanges the API key for a LiveKit token
3. The client connects via WebRTC — mic and agent audio are automatic
4. Bidirectional communication happens over a data channel (client actions)

### Authentication
```
API Key format: vb_<random_string>

# Token endpoint
POST https://vocalbridgeai.com/api/v1/token
Headers:
  X-API-Key: vb_your_api_key
  Content-Type: application/json
Body: { "participant_name": "User" }

Response: { "livekit_url", "token", "room_name", "participant_identity", "expires_in", "agent_mode" }
```

**Security:** Never expose API keys client-side. Always proxy through your backend.

### JavaScript SDK
```bash
npm install @vocalbridgeai/sdk
```

```javascript
import { VocalBridge } from '@vocalbridgeai/sdk';

const vb = new VocalBridge({
  auth: { tokenUrl: '/api/voice-token' },
  participantName: 'User',
  debug: true,
});

vb.on('connectionStateChanged', (state) => {
  // disconnected → connecting → waiting_for_agent → connected
});

vb.on('transcript', ({ role, text }) => {
  console.log(`${role === 'user' ? 'You' : 'Agent'}: ${text}`);
});

vb.on('agentAction', ({ action, payload }) => {
  // Handle custom actions from the agent
});

await vb.connect();
```

### React SDK
```bash
npm install @vocalbridgeai/sdk @vocalbridgeai/react
```

```jsx
import { VocalBridgeProvider, useVocalBridge, useTranscript, useAgentActions, useAIAgent } from '@vocalbridgeai/react';

function App() {
  return (
    <VocalBridgeProvider options={{ auth: { tokenUrl: '/api/voice-token' } }}>
      <VoiceChat />
    </VocalBridgeProvider>
  );
}

function VoiceChat() {
  const { state, connect, disconnect, toggleMicrophone } = useVocalBridge();
  const { transcript } = useTranscript();

  useAIAgent({
    onQuery: async (query) => {
      // Forward to your AI agent that calls Sabre APIs
      return await myTravelAgent.ask(query);
    },
  });

  // ... render UI
}
```

### Python SDK
```bash
pip install livekit requests
```

```python
import requests

VOCAL_BRIDGE_API_KEY = os.environ.get('VOCAL_BRIDGE_API_KEY')

def get_voice_token(participant_name='User'):
    response = requests.post(
        'https://vocalbridgeai.com/api/v1/token',
        headers={'X-API-Key': VOCAL_BRIDGE_API_KEY, 'Content-Type': 'application/json'},
        json={'participant_name': participant_name}
    )
    return response.json()
```

### Backend Token Endpoint (Node.js)
```javascript
// /api/voice-token
app.get('/api/voice-token', async (req, res) => {
  const response = await fetch('https://vocalbridgeai.com/api/v1/token', {
    method: 'POST',
    headers: {
      'X-API-Key': process.env.VOCAL_BRIDGE_API_KEY,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ participant_name: 'User' })
  });
  res.json(await response.json());
});
```

### Next.js API Route
```typescript
// app/api/voice-token/route.ts
import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  const body = await request.json();
  const response = await fetch('https://vocalbridgeai.com/api/v1/token', {
    method: 'POST',
    headers: {
      'X-API-Key': process.env.VOCAL_BRIDGE_API_KEY!,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ participant_name: body.participant_name || 'Web User' }),
  });
  return NextResponse.json(await response.json());
}
```

### AI Agent Integration (Critical for this hackathon)

The voice agent delegates domain questions to YOUR agent via data channel:

```javascript
// Voice agent sends query:
{ "type": "client_action", "action": "query_agent", "payload": { "query": "...", "turn_id": "abc123" } }

// Your agent responds:
{ "type": "client_action", "action": "agent_response", "payload": { "response": "...", "turn_id": "abc123" } }
```

**SDK helper (automatic mode):**
```javascript
vb.onAIAgentQuery(async (query) => {
  // Call Sabre APIs based on the query, return spoken response
  return await travelAgent.process(query);
});
```

### Client Actions (Bidirectional)

Agent-to-App (show UI elements):
```javascript
vb.on('agentAction', ({ action, payload }) => {
  if (action === 'show_flight_options') renderFlights(payload);
  if (action === 'show_itinerary') renderItinerary(payload);
  if (action === 'confirm_booking') showConfirmation(payload);
});
```

App-to-Agent (user interactions):
```javascript
await vb.sendAction('flight_selected', { flightId: 'AA123', price: 450 });
await vb.sendAction('confirm_booking', { itineraryId: 'trip-001' });
```

### CLI Tool
```bash
pip install vocal-bridge

vb auth login vb_your_api_key
vb agent                    # Show agent info
vb agent create             # Create new agent
vb config set --style Chatty
vb config set --ai-agent-enabled true --ai-agent-description "Travel booking agent"
vb prompt edit              # Edit system prompt
vb debug                    # Stream real-time debug events
vb logs                     # View call logs
vb mcp test "book a flight" # Test without a call
```

### Custom HTTP API Tools

Register Sabre APIs as tools the voice agent can call directly:
```json
[
  {
    "name": "search_flights",
    "description": "Search for available flights between cities",
    "method": "POST",
    "url": "https://your-backend.com/api/sabre/flights",
    "auth": { "type": "bearer", "credentials": { "token": "your-internal-key" } },
    "parameters": [
      { "name": "origin", "type": "string", "required": true, "location": "body" },
      { "name": "destination", "type": "string", "required": true, "location": "body" },
      { "name": "date", "type": "string", "required": true, "location": "body" }
    ]
  }
]
```

### MCP Integration

Connect MCP servers for extended capabilities:
```bash
vb config set --mcp-servers-file servers.json
```

### Post-Processing (After calls)

Automatically summarize calls, extract bookings, send confirmations:
```bash
vb config set --post-processing-prompt "Extract all bookings from the call and send confirmation emails"
vb config set --post-processing-model gemini-2.5-flash
```

### Environment Variables
```bash
VOCALBRIDGE_API_KEY=vb_<your_key>
VOCALBRIDGE_BASE_URL=https://api.vocalbridge.ai
VOCALBRIDGE_AGENT_ID=<from dashboard>
DEMO_USER_PHONE=+15551234567              # E.164 format
PUBLIC_BASE_URL=https://your.ngrok.app    # for webhook delivery
```

### Already-Implemented (in vocalbridge.py)
- **Outbound call:** `POST {VB_BASE_URL}/v1/calls` with `agent_id`, `to`, `first_message`, `webhook_url`
- **Webhook parsing:** normalizes events into `{type, role, text, call_id}`
- **Webhook types:** `transcript` (user/agent speech), `call_ended`

---

## Recommended Stack

### Option A: Next.js (Fastest to prototype)
```
Next.js App Router + React SDK + Vocal Bridge + Sabre APIs
├── app/api/voice-token/route.ts   (token proxy)
├── app/api/sabre/[...path]/route.ts (Sabre proxy)
├── app/page.tsx                    (voice UI)
└── lib/travel-agent.ts            (AI agent logic)
```

### Option B: Python Backend + Any Frontend
```
Flask/FastAPI + LiveKit Python SDK + Sabre APIs
├── server.py          (token + Sabre endpoints)
├── agent.py           (AI agent with tool use)
└── frontend/          (React/vanilla with JS SDK)
```

---

## Hackathon Ideas (from event brief)

1. **Multilingual Travel Concierge** — Agent that speaks Japanese and English to handle hotel issues in Osaka at 2am
2. **Hold-for-Me Agent** — Calls the airline on your behalf, waits on hold, speaks to the human agent to rebook cancelled flights
3. **Full Trip Builder** — "Plan me a weekend in Austin" → books flight + hotel + dinner + concert in one conversation
4. **Group Trip Coordinator** — Manages bookings for multiple travelers, finds overlapping availability
5. **Travel Emergency Agent** — Handles cancellations, rebookings, and alternatives when things go wrong mid-trip

---

## Key SDK Events Reference

| Event | Payload | Use For |
|-------|---------|---------|
| `connectionStateChanged` | ConnectionState | UI state management |
| `transcript` | `{ role, text, timestamp }` | Live conversation display |
| `agentAction` | `{ action, payload }` | Agent-driven UI updates |
| `aiAgentQuery` | `{ query, turnId }` | Delegating to your AI |
| `error` | VocalBridgeError | Error handling |

## Error Codes

| Code | Meaning |
|------|---------|
| `TOKEN_FETCH_FAILED` | Token request failed |
| `CONNECTION_FAILED` | WebRTC connection failed |
| `MICROPHONE_ERROR` | Mic access denied |
| `USAGE_LIMIT_EXCEEDED` | 403 from token endpoint |
| `AGENT_NOT_FOUND` | Agent ID doesn't exist |
| `AGENT_NOT_ACTIVE` | Agent exists but isn't running |

---

## Quick Start Checklist

- [ ] Get Sabre Dev Studio credentials (client ID + secret)
- [ ] Get Vocal Bridge API key from dashboard
- [ ] Set up backend token endpoint
- [ ] Install SDK (`@vocalbridgeai/sdk` or `pip install vocal-bridge`)
- [ ] Connect voice + wire up AI agent query handler
- [ ] Implement Sabre API calls in the agent logic
- [ ] Add client actions for visual UI (flight cards, itinerary view)
- [ ] Test with `vb debug` for real-time event streaming

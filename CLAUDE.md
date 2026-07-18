# Hackathon: Voice AI Travel Agent — "Tailwind AI"

## Project Goal

Build a voice-powered AI travel agent that unifies flights, hotels, ground transport, dining, and experiences into a single spoken conversation. The agent should book and manage a complete trip itinerary by voice — not a chatbot, not a notification, but a real voice agent.

**Required integrations:** Sabre Agentic APIs (travel) + Vocal Bridge (voice AI layer)

---

## Current Implementation

The app already implements a **proactive flight-disruption rebooking flow**:

1. Flight gets cancelled → agent calls the traveler (Vocal Bridge outbound)
2. Traveler says "yes" → Sabre search for alternatives → agent picks the best one → Sabre books it (simulated by default)
3. Web UI shows old vs. new itinerary cards in real-time

**State machine:** `idle → calling → awaiting_confirmation → rebooking → done` (or `declined` / `error`)

### Files
| File | Role |
|------|------|
| `main.py` | FastAPI app: routes, in-memory state, orchestration |
| `agent.py` | Agent logic (rule-based): opening line, intent detection, flight selection |
| `sabre.py` | SabreClient: Bearer auth + flight search (InstaFlights/BFM) + booking (Create PNR) |
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
User (voice) <-> Vocal Bridge (WebRTC/outbound call) <-> Our Agent (rule-based) <-> Sabre APIs (travel data/booking)
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

## Vocal Bridge (Voice AI Layer) — Full Developer Guide

Vocal Bridge provides voice AI agents that you can integrate into any application using WebRTC. Users can have real-time voice conversations with AI agents through web browsers, mobile apps, or any platform that supports WebRTC.

- **Real-time Voice** — Sub-second latency voice AI using WebRTC
- **Secure API Keys** — Production-ready authentication
- **Multi-platform** — JavaScript, Python, React, Flutter, and more

### Quick Start

1. **Create an API Key** — Go to your agent's page, open Developer Mode, click "Create API Key"
2. **Install the SDK** — `npm install @vocalbridgeai/sdk`
3. **Connect:**
```javascript
import { VocalBridge } from '@vocalbridgeai/sdk';

const vb = new VocalBridge({
  auth: { tokenUrl: '/api/voice-token' },
});

vb.on('transcript', ({ role, text }) => {
  console.log(`[${role}] ${text}`);
});

await vb.connect();
// Agent audio plays automatically. Mic is live.
```

The SDK handles token exchange, WebRTC connections, audio playback, heartbeats, and transcript accumulation automatically.

### Authentication

API keys start with `vb_` followed by a secure random string.

**Security: Never expose your API key in client-side code. Always call the token endpoint from your backend.**

```bash
# Option 1: X-API-Key header (recommended)
curl -H "X-API-Key: vb_your_api_key" http://vocalbridgeai.com/api/v1/token

# Option 2: Authorization header
curl -H "Authorization: Bearer vb_your_api_key" http://vocalbridgeai.com/api/v1/token
```

**Account-Level API Keys** work across all your agents — include `X-Agent-Id` header:
```bash
curl -H "X-API-Key: vb_your_account_key" \
     -H "X-Agent-Id: your-agent-uuid" \
     http://vocalbridgeai.com/api/v1/token
```

**SDK Auth Strategies:**
```javascript
// 1. Token URL (production — recommended)
{ auth: { tokenUrl: '/api/voice-token' } }

// 2. API Key (prototyping only — exposes key to browser)
{ auth: { apiKey: 'vb_xxx', agentId: 'your-agent-uuid' } }

// 3. Custom provider (maximum flexibility)
{ auth: { tokenProvider: async () => ({ url, token, room_name, ... }) } }
```

### API Reference

#### POST /api/v1/token
Generate a LiveKit access token for connecting to the agent.

**Request Headers:**
- `X-API-Key` — Your API key (required)
- `X-Agent-Id` — Agent UUID (required for account-level API keys)
- `Content-Type` — application/json

**Request Body (optional):**
- `participant_name` (string) — Display name (default: "API Client")
- `session_id` (string) — Custom session ID (default: auto-generated)

**Response:**
```json
{
  "livekit_url": "wss://tutor-j7bhwjbm.livekit.cloud",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "room_name": "user-abc-agent-xyz-api-12345",
  "participant_identity": "api-client-xxxx-12345",
  "expires_in": 3600,
  "agent_mode": "cascaded_concierge"
}
```

#### GET /api/v1/agent
Get information about the agent associated with your API key.

**Response:**
```json
{
  "id": "uuid",
  "name": "My Voice Agent",
  "mode": "cascaded_concierge",
  "deployment_status": "active",
  "phone_number": "+1234567890",
  "greeting": "Hello! How can I help you?",
  "background_enabled": true,
  "hold_enabled": false,
  "hangup_enabled": false,
  "created_at": "2025-01-14T12:00:00Z"
}
```

### JavaScript SDK

```bash
npm install @vocalbridgeai/sdk
```

**Complete Example:**
```javascript
import { VocalBridge } from '@vocalbridgeai/sdk';

const vb = new VocalBridge({
  auth: { tokenUrl: '/api/voice-token' },
  participantName: 'User',
  debug: true,
});

// Connection state
vb.on('connectionStateChanged', (state) => {
  // disconnected → connecting → waiting_for_agent → connected
});

// Live transcript (automatic — no setup needed)
vb.on('transcript', ({ role, text }) => {
  console.log(`${role === 'user' ? 'You' : 'Agent'}: ${text}`);
});

// Custom agent actions
vb.on('agentAction', ({ action, payload }) => {
  if (action === 'show_product') showProductModal(payload);
});

// Errors
vb.on('error', (err) => {
  console.error(err.code, err.message);
});

// Connect — mic and agent audio are handled automatically
await vb.connect();

// Send actions to the agent
await vb.sendAction('user_clicked_buy', { productId: '123' });

// Mute/unmute
await vb.toggleMicrophone();

// Disconnect
await vb.disconnect();
```

**SDK Options:**
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `auth` | AuthConfig | required | Authentication strategy |
| `participantName` | string | "User" | Display name |
| `sessionId` | string | auto | Custom session ID |
| `autoAckHeartbeat` | boolean | true | Auto-acknowledge agent heartbeats |
| `autoPlayAudio` | boolean | true | Auto-play agent audio |
| `maxReconnectAttempts` | number | 3 | Max reconnect retries |
| `debug` | boolean | false | Console logging |

**SDK Methods:**
| Method | Description |
|--------|-------------|
| `connect()` | Connect to the voice agent |
| `disconnect()` | Disconnect and clean up |
| `setMicrophoneEnabled(enabled)` | Mute/unmute mic |
| `toggleMicrophone()` | Toggle mic state |
| `sendAction(action, payload?)` | Send custom action to agent |
| `sendAIAgentResponse(turnId, response)` | Respond to AI agent query |
| `onAIAgentQuery(handler)` | Register auto-response handler |
| `clearTranscript()` | Clear accumulated transcript |
| `on(event, handler)` | Subscribe to event |
| `off(event, handler)` | Unsubscribe from event |

**SDK Events:**
| Event | Payload | Description |
|-------|---------|-------------|
| `connectionStateChanged` | ConnectionState | State transition |
| `transcript` | `{ role, text, timestamp }` | New transcript entry |
| `agentAction` | `{ action, payload }` | Custom agent action |
| `heartbeat` | `{ timestamp, agent_identity }` | Agent heartbeat |
| `aiAgentQuery` | `{ query, turnId }` | AI agent query |
| `microphoneChanged` | boolean | Mic state change |
| `error` | VocalBridgeError | Error occurred |

**SDK Error Codes:**
| Code | When |
|------|------|
| `TOKEN_FETCH_FAILED` | Token request failed (network, 401, etc.) |
| `CONNECTION_FAILED` | WebRTC connection failed |
| `MICROPHONE_ERROR` | Mic access denied or unavailable |
| `DATA_CHANNEL_ERROR` | Failed to send data to agent |
| `RECONNECT_FAILED` | All reconnection attempts exhausted |
| `USAGE_LIMIT_EXCEEDED` | 403 from token endpoint |
| `AGENT_NOT_FOUND` | 404 — agent ID doesn't exist |
| `AGENT_NOT_ACTIVE` | Agent exists but isn't active |

### Backend Token Endpoint (Node.js/Express)
```javascript
const express = require('express');
const app = express();

const VOCAL_BRIDGE_API_KEY = process.env.VOCAL_BRIDGE_API_KEY;

app.get('/api/voice-token', async (req, res) => {
  try {
    const response = await fetch('https://vocalbridgeai.com/api/v1/token', {
      method: 'POST',
      headers: {
        'X-API-Key': VOCAL_BRIDGE_API_KEY,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        participant_name: req.user?.name || 'User'
      })
    });
    const data = await response.json();
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: 'Failed to get voice token' });
  }
});

app.listen(3000);
```

### Next.js API Route
```typescript
// app/api/voice-token/route.ts (Next.js App Router)
import { NextRequest, NextResponse } from 'next/server';

const VOCAL_BRIDGE_API_KEY = process.env.VOCAL_BRIDGE_API_KEY!;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const response = await fetch('https://vocalbridgeai.com/api/v1/token', {
      method: 'POST',
      headers: {
        'X-API-Key': VOCAL_BRIDGE_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        participant_name: body.participant_name || 'Web User',
      }),
    });
    if (!response.ok) throw new Error('Failed to get token');
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json({ error: 'Failed to get voice token' }, { status: 500 });
  }
}
```

### Python SDK

```bash
pip install livekit requests
```

**Complete Example:**
```python
import asyncio
import os
import requests
from livekit import rtc

VOCAL_BRIDGE_API_KEY = os.environ.get('VOCAL_BRIDGE_API_KEY')
VOCAL_BRIDGE_URL = 'http://vocalbridgeai.com'


def get_voice_token(participant_name: str = 'Python Client'):
    response = requests.post(
        f'{VOCAL_BRIDGE_URL}/api/v1/token',
        headers={
            'X-API-Key': VOCAL_BRIDGE_API_KEY,
            'Content-Type': 'application/json'
        },
        json={'participant_name': participant_name}
    )
    response.raise_for_status()
    return response.json()


async def main():
    token_data = get_voice_token()
    room = rtc.Room()

    @room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_stream = rtc.AudioStream(track)

    @room.on("disconnected")
    def on_disconnected():
        print("Disconnected from room")

    await room.connect(token_data['livekit_url'], token_data['token'])

    source = rtc.AudioSource(sample_rate=48000, num_channels=1)
    track = rtc.LocalAudioTrack.create_audio_track("microphone", source)
    await room.local_participant.publish_track(track)

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await room.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
```

**Flask Backend Example:**
```python
from flask import Flask, jsonify
import requests
import os

app = Flask(__name__)

VOCAL_BRIDGE_API_KEY = os.environ.get('VOCAL_BRIDGE_API_KEY')
VOCAL_BRIDGE_URL = 'http://vocalbridgeai.com'

@app.route('/api/voice-token')
def get_voice_token():
    response = requests.post(
        f'{VOCAL_BRIDGE_URL}/api/v1/token',
        headers={
            'X-API-Key': VOCAL_BRIDGE_API_KEY,
            'Content-Type': 'application/json'
        },
        json={'participant_name': 'Web User'}
    )
    return jsonify(response.json())

if __name__ == '__main__':
    app.run(port=5000)
```

### React Integration

```bash
npm install @vocalbridgeai/sdk @vocalbridgeai/react
```

**Complete Example:**
```jsx
import { VocalBridgeProvider, useVocalBridge, useTranscript, useAgentActions, useAIAgent } from '@vocalbridgeai/react';
import { ConnectionState } from '@vocalbridgeai/sdk';

function App() {
  return (
    <VocalBridgeProvider options={{ auth: { tokenUrl: '/api/voice-token' } }}>
      <VoiceChat />
    </VocalBridgeProvider>
  );
}

function VoiceChat() {
  const { state, connect, disconnect, isMicrophoneEnabled, toggleMicrophone, error } = useVocalBridge();
  const { transcript } = useTranscript();
  const { onAction, sendAction } = useAgentActions();

  useEffect(() => {
    return onAction('show_product', (payload) => {
      showProductModal(payload);
    });
  }, [onAction]);

  useAIAgent({
    onQuery: async (query) => {
      return await myAgent.ask(query);
    },
  });

  return (
    <div>
      <p>Status: {state}</p>
      {error && <p style={{ color: 'red' }}>{error.message}</p>}
      {state === ConnectionState.Disconnected ? (
        <button onClick={connect}>Start Voice Chat</button>
      ) : (
        <>
          <button onClick={disconnect}>End Call</button>
          <button onClick={toggleMicrophone}>
            {isMicrophoneEnabled ? 'Mute' : 'Unmute'}
          </button>
        </>
      )}
      {transcript.map((entry, i) => (
        <p key={i}>
          <strong>{entry.role === 'user' ? 'You' : 'Agent'}:</strong> {entry.text}
        </p>
      ))}
    </div>
  );
}
```

**React Hooks Reference:**

`useVocalBridge()` — Primary hook for connection lifecycle, mic control, and sending actions:
```javascript
const {
  state,                // ConnectionState
  connect,              // () => Promise<void>
  disconnect,           // () => Promise<void>
  isMicrophoneEnabled,  // boolean
  toggleMicrophone,     // () => Promise<void>
  setMicrophoneEnabled, // (enabled: boolean) => Promise<void>
  sendAction,           // (action: string, payload?: object) => Promise<void>
  agentMode,            // string | undefined
  error,                // VocalBridgeError | null
  client,               // VocalBridge instance (advanced)
} = useVocalBridge();
```

`useTranscript()` — Live conversation transcript:
```javascript
const { transcript, clear } = useTranscript();
// transcript: Array<{ role: 'user' | 'agent', text: string, timestamp: number }>
```

`useAgentActions()` — Bidirectional custom actions:
```javascript
const { lastAction, sendAction, onAction } = useAgentActions();

useEffect(() => {
  return onAction('show_product', (payload) => {
    setProduct(payload);
  });
}, [onAction]);

sendAction('user_clicked_buy', { productId: '123' });
```

`useAIAgent()` — AI Agent integration:
```javascript
// Automatic (callback):
useAIAgent({
  onQuery: async (query) => {
    return await myAgent.ask(query);
  },
});

// Manual:
const { pendingQuery, respond } = useAIAgent();
useEffect(() => {
  if (pendingQuery) {
    myAgent.ask(pendingQuery.query).then(answer => {
      respond(pendingQuery.turnId, answer);
    });
  }
}, [pendingQuery]);
```

### Flutter SDK

Add to `pubspec.yaml`:
```yaml
dependencies:
  livekit_client: ^2.3.0
  http: ^1.2.0
```

**Complete Example:**
```dart
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:livekit_client/livekit_client.dart';

class VoiceAgentService {
  Room? _room;
  EventsListener<RoomEvent>? _listener;

  Future<Map<String, dynamic>> _getTokenFromBackend() async {
    final response = await http.get(
      Uri.parse('https://your-backend.com/api/voice-token'),
    );
    return jsonDecode(response.body);
  }

  Future<void> connect() async {
    final tokenData = await _getTokenFromBackend();
    final livekitUrl = tokenData['livekit_url'] as String;
    final token = tokenData['token'] as String;

    _room = Room();

    _listener = _room!.createListener();
    _listener!.on<TrackSubscribedEvent>((event) {
      if (event.track.kind == TrackType.AUDIO) {
        print('Agent audio track subscribed');
      }
    });

    _listener!.on<RoomDisconnectedEvent>((event) {
      print('Disconnected from room');
    });

    await _room!.connect(livekitUrl, token);
    await _room!.localParticipant?.setMicrophoneEnabled(true);
  }

  Future<void> disconnect() async {
    await _room?.disconnect();
    _room = null;
    _listener = null;
  }

  bool get isConnected => _room?.connectionState == ConnectionState.connected;
}
```

**Handling Client Actions (Flutter):**
```dart
void _setupClientActionHandler() {
  _listener!.on<DataReceivedEvent>((event) {
    if (event.topic == 'client_actions') {
      final data = jsonDecode(utf8.decode(event.data));
      if (data['type'] == 'client_action') {
        _handleAgentAction(data['action'], data['payload']);
      }
    }
  });
}

Future<void> sendActionToAgent(String action, [Map<String, dynamic>? payload]) async {
  final message = jsonEncode({
    'type': 'client_action',
    'action': action,
    'payload': payload ?? {},
  });
  await _room?.localParticipant?.publishData(
    utf8.encode(message),
    reliable: true,
    topic: 'client_actions',
  );
}
```

**Platform Setup:**

iOS — Add to `ios/Runner/Info.plist`:
```xml
<key>NSMicrophoneUsageDescription</key>
<string>This app needs microphone access for voice chat</string>
<key>UIBackgroundModes</key>
<array><string>audio</string></array>
```

Android — Add to `AndroidManifest.xml`:
```xml
<uses-permission android:name="android.permission.RECORD_AUDIO"/>
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS"/>
```

### Client Actions

Client Actions enable bidirectional communication between your voice agent and your client application via LiveKit's data channel.

**Directions:**
- **Agent to App:** The agent triggers actions in your client (navigate, show product card, update UI)
- **App to Agent:** Your client sends events to the agent (user clicked button, form submitted)

**Behavior (App to Agent):**
- `respond` (default) — Agent generates a reply when this event arrives
- `notify` — Event is silently added to conversation context; agent sees it on next turn but does not reply immediately

```javascript
// Receive actions from agent
vb.on('agentAction', ({ action, payload }) => {
  switch (action) {
    case 'navigate': window.location.href = payload.url; break;
    case 'show_product': showProductModal(payload.product_id); break;
  }
});

// Send actions to agent
await vb.sendAction('user_clicked_buy', { productId: '123', quantity: 2 });
await vb.sendAction('practice_result', { score: 95, word: 'hello' });
```

**Configure via CLI:**
```bash
vb config set --client-actions-file client_actions.json

# Example client_actions.json:
# [
#   {"name": "show_product", "description": "Display a product card", "direction": "agent_to_app"},
#   {"name": "user_clicked_buy", "description": "User clicked buy", "direction": "app_to_agent", "behavior": "respond"},
#   {"name": "practice_result", "description": "Practice completed", "direction": "app_to_agent", "behavior": "notify"}
# ]
```

### Live Transcript (Built-in)

All Vocal Bridge agents automatically send a `send_transcript` event whenever the user speaks or the agent responds. No setup required.

**Message Format:**
```json
{
  "type": "client_action",
  "action": "send_transcript",
  "payload": {
    "role": "user",
    "text": "Hello, how are you?",
    "timestamp": 1708123456789
  }
}
```

**Using the SDK:**
```javascript
vb.on('transcript', ({ role, text, timestamp }) => {
  console.log(`${role === 'user' ? 'You' : 'Agent'}: ${text}`);
});

console.log(vb.transcript);  // Full conversation history
vb.clearTranscript();
```

**React:**
```jsx
const { transcript, clear } = useTranscript();
return (
  <div>
    {transcript.map((entry, i) => (
      <p key={i}>
        <strong>{entry.role === 'user' ? 'You' : 'Agent'}:</strong> {entry.text}
      </p>
    ))}
    <button onClick={clear}>Clear</button>
  </div>
);
```

### Listener Mode

Listener mode is a passive-observer agent: it joins the room, transcribes multi-speaker audio with speaker diarization, and streams coaching suggestions via the data channel. It never speaks. Use for live coaching during investor calls, sales calls, interviews.

Create with `vb agent create --style Listener` or pick "Listener" in the dashboard.

**Three built-in actions:**

**`live_transcript`** — Fires for interim and final transcript segments:
```json
{
  "type": "client_action",
  "action": "live_transcript",
  "payload": {
    "speaker_id": "S0",
    "text": "...",
    "is_final": true,
    "timestamp": 1708123456789
  }
}
```

**`coaching_suggestion`** — Fires when the latest turn matches your coaching policy:
```json
{
  "type": "client_action",
  "action": "coaching_suggestion",
  "payload": {
    "speaker_id": "S0",
    "question_text": "What was your Q3 margin?",
    "guidance": "**Lead with:** Margins expanded 120bps YoY...",
    "format": "markdown",
    "timestamp": 1708123456789,
    "job_id": "..."
  }
}
```

**`speaker_map_update`** — Periodic inferred mapping from speaker IDs to names/roles:
```json
{
  "type": "client_action",
  "action": "speaker_map_update",
  "payload": {
    "mapping": {
      "S0": {"name": "Jane Doe", "org": "Morgan Stanley", "role": "analyst", "confidence": 0.9},
      "S1": {"name": null, "org": null, "role": "executive", "confidence": 0.4}
    },
    "timestamp": 1708123456789
  }
}
```

**Subscribing (JavaScript SDK):**
```javascript
vb.on('agentAction', ({ action, payload }) => {
  switch (action) {
    case 'live_transcript': {
      const { speaker_id, text, is_final } = payload;
      if (is_final) appendFinal(speaker_id, text);
      else updateInterim(text);
      break;
    }
    case 'coaching_suggestion':
      renderCoachingCard(payload);
      break;
    case 'speaker_map_update':
      refreshSpeakerLabels(payload.mapping);
      break;
  }
});
await vb.connect();
```

**Listener Settings:**
| Setting | Range | Default | What it does |
|---------|-------|---------|--------------|
| `coaching.coachee_description` | text, ≤500 chars | empty | Names the person being coached |
| `coaching.debounce_seconds` | 0–60 | 12 | Min seconds between coaching cards |
| `coaching.context_turns` | 0–50 | 10 | Recent turns considered per card |
| `coaching.job_timeout_seconds` | 5–120 | 30 | Max seconds per card |
| `coaching.gate_enabled` | true/false | true | Only coach when trigger conditions match |
| `speaker_map.enabled` | true/false | true | Identify who's speaking |
| `speaker_map.update_interval_seconds` | 5–300 | 20 | How often to re-check identities |

```bash
vb config set --coachee-description "the CFO during earnings Q&A" \
              --coaching-debounce 8 \
              --coaching-gate true
```

### MCP Tools

The Model Context Protocol (MCP) allows your voice agent to connect to external tools and services.

**Quick Setup with Zapier:**
1. Go to zapier.com/mcp
2. Configure the apps to connect
3. Copy your MCP server URL
4. Paste into your agent's MCP Server URL field

**Custom MCP Server:** Build your own using the MCP specification. Must support Streamable HTTP transport.

```bash
vb config set --mcp-servers-file servers.json
```

### Native Connectors

Platform-managed OAuth connectors — no MCP server to host, no API keys to manage.

**Available Connectors:**
- Google Calendar — read and create calendar events
- Gmail — send email and create drafts
- Linear — create, search, and update issues

```bash
vb connectors list
vb connectors connect google_calendar
vb config get connectors > connectors.json
vb config set --connectors-file connectors.json --merge
```

### Custom HTTP API Tools

Let your agent call external REST APIs during conversations.

**Supported:** GET, POST, PUT, DELETE, PATCH
**Auth Types:** Bearer token, Basic auth, Custom header, Query parameter, None
**Reliability:** Configurable timeout (1-300s) and retry count (0-5)

```json
[
  {
    "id": "1",
    "name": "get_weather",
    "description": "Get the current weather for a city",
    "method": "GET",
    "url": "https://api.weather.com/v1/current",
    "auth": {
      "type": "bearer",
      "credentials": { "token": "your-api-key" }
    },
    "parameters": [
      {
        "name": "city",
        "type": "string",
        "description": "City name",
        "required": true,
        "location": "query"
      }
    ],
    "timeout": 30,
    "max_retries": 2,
    "enabled": true
  }
]
```

**Auth type reference:**
| Type | Credentials | Behavior |
|------|------------|----------|
| `bearer` | `{"token": "sk-xxx"}` | Authorization: Bearer sk-xxx |
| `basic` | `{"username": "u", "password": "p"}` | Base64-encoded Basic auth |
| `header` | `{"header_name": "X-Key", "header_value": "val"}` | Custom HTTP header |
| `query` | `{"param_name": "key", "param_value": "val"}` | Query parameter |
| `none` | N/A | No authentication |

```bash
vb config set --api-tools-file api_tools.json
```

**Limits:** Max 20 tools per agent. URLs must use HTTPS. Credentials encrypted at rest.

### Post-Processing

Runs automatically after each call ends. Summarize conversations, update CRM, send follow-ups, create tickets.

**Configuration:**
- **Post-Processing Prompt** — Tell the LLM what to do with the transcript
- **Post-Processing MCP Server** — Optional separate MCP server for post-call actions
- **Model:** `auto` (default), `gemini-2.5-flash`, `gemini-2.5-flash-lite`

```bash
vb config set --post-processing-prompt "Summarize the call and extract action items"
vb config set --post-processing-mcp-url "https://your-mcp-server.com/..."
vb config set --post-processing-model gemini-2.5-flash
```

**Test:** `vb post-processing test [transcript]`

### AI Agents

Connect your existing AI agent to a Vocal Bridge voice agent. The voice agent handles conversation flow, greetings, and filler while delegating domain-specific questions to your agent.

**How It Works:**
1. User asks a domain-specific question
2. Voice agent sends `query_agent` via data channel
3. Your app forwards to your AI agent
4. Your app sends response back via `agent_response`
5. Voice agent speaks the response

**Data Channel Protocol:**
```json
// Query from voice agent:
{ "type": "client_action", "action": "query_agent", "payload": { "query": "What appointments do I have?", "turn_id": "abc123" } }

// Response from your agent:
{ "type": "client_action", "action": "agent_response", "payload": { "response": "You have a dentist at 10am.", "turn_id": "abc123" } }
```

**SDK (Automatic mode):**
```javascript
vb.onAIAgentQuery(async (query) => {
  const response = await myAgent.ask(query);
  return response;
});
await vb.connect();
```

**SDK (Manual mode):**
```javascript
vb.on('aiAgentQuery', async ({ query, turnId }) => {
  const answer = await myAgent.ask(query);
  vb.sendAIAgentResponse(turnId, answer);
});
```

**Configuration:**
```json
{
  "enabled": true,
  "description": "Customer support agent for Acme Corp",
  "verbatim": false
}
```
- `enabled` — Whether AI Agent integration is active
- `description` — What your agent does (max 2000 chars). Guides voice agent on when to delegate
- `verbatim` — If true, speaks responses exactly. If false (default), adapts for natural voice

```bash
vb config set --ai-agent-enabled true --ai-agent-description "Travel booking agent"
```

**Notes:** Timeout is 60 seconds. Works with web deploy targets only (requires data channel).

### Troubleshooting

| Problem | Solution |
|---------|----------|
| 403 Forbidden | API key invalid or revoked. Check dashboard |
| No audio from agent | Ensure `autoPlayAudio` not false. Call `connect()` from user gesture |
| Microphone not working | Browser needs permission. Listen for `MICROPHONE_ERROR` |
| Token expired | Tokens valid 1 hour. Call `disconnect()` then `connect()` for fresh token |
| CORS errors | Don't call API from browser. Use `tokenUrl` with backend endpoint |

### CLI

```bash
pip install vocal-bridge
```

**Authentication:**
```bash
vb auth login                      # Interactive
vb auth login vb_your_api_key      # Direct
vb agent use                       # Select agent (for account keys)
vb auth status                     # Check status
```

**Commands:**
| Command | Description |
|---------|-------------|
| `vb agent` | Show current agent info |
| `vb agent list` | List all agents |
| `vb agent use` | Select an agent |
| `vb agent create` | Create and deploy a new agent (paid plans only) |
| `vb logs` | List recent call logs |
| `vb logs show <id>` | View call details and transcript |
| `vb logs download <id>` | Download call recording |
| `vb stats` | Show call statistics |
| `vb prompt show` | View current prompt and greeting |
| `vb prompt edit` | Edit prompt in $EDITOR |
| `vb prompt set --file` | Set prompt from file or stdin |
| `vb config show` | View all agent settings |
| `vb config get <section>` | Export a config section as JSON |
| `vb config edit` | Edit full config in $EDITOR (JSON) |
| `vb config set` | Update individual settings |
| `vb config options` | Discover valid values for settings |
| `vb mcp test <query>` | Test background AI and MCP/API tools |
| `vb post-processing test` | Run post-call processing against a transcript |
| `vb connectors list` | List native connectors |
| `vb connectors connect <key>` | Connect a connector via OAuth |
| `vb call <phone>` | Place an outbound call (paid plans only) |
| `vb eval <session_id>` | Evaluate a call recording (paid plans, 100/day) |
| `vb debug` | Stream real-time debug events |
| `vb docs` | Get developer integration docs |

**Update Settings:**
```bash
vb config set --style Chatty
vb config set --debug-mode true
vb config set --hold-enabled true
vb config set --max-call-duration 15
vb config set --max-history-messages 50
vb config set --background-model auto  # auto | claude-haiku-4-5 | claude-sonnet-4-6
vb config set --continuous-mode true
vb config set --continuous-mode true --continuous-mode-delay 3
vb config set --outbound-wait-for-user true
```

**Continuous mode:** Agent keeps talking on its own after a short silence — great for tutors, narrators, guided experiences. User can always interrupt by speaking. With continuous mode off (default), agent takes turns normally.

**Evaluate a Call:**
```bash
vb eval <session_id>
vb eval <session_id> --objective "Schedule an interview for next Tuesday"
vb eval <session_id> --objective "Confirm availability" --scenario "User is busy and tries to reschedule twice"
vb eval <session_id> --json
```

**Environment Variables:**
```bash
export VOCAL_BRIDGE_API_KEY=vb_your_api_key_here
export VOCAL_BRIDGE_API_URL=https://vocalbridgeai.com  # optional
```

### Claude Code Plugin

Install the plugin for native slash commands:
```bash
/plugin marketplace add vocalbridgeai/vocal-bridge-marketplace
/plugin install vocal-bridge@vocal-bridge
```

**Getting Started:**
```bash
/vocal-bridge:login vb_your_api_key_here
```

**Available Commands:**
| Command | Description |
|---------|-------------|
| `/vocal-bridge:login` | Authenticate with your API key |
| `/vocal-bridge:status` | Check authentication status |
| `/vocal-bridge:agent` | Show agent information |
| `/vocal-bridge:create` | Create and deploy a new agent |
| `/vocal-bridge:logs` | View call logs and transcripts |
| `/vocal-bridge:download` | Download call recording |
| `/vocal-bridge:stats` | Show call statistics |
| `/vocal-bridge:prompt` | View or update system prompt |
| `/vocal-bridge:config` | View and update agent configuration |
| `/vocal-bridge:eval <session_id>` | Evaluate a call recording |
| `/vocal-bridge:debug` | Stream real-time debug events |
| `/vocal-bridge:help` | Show all available commands |

### Advanced: Direct WebRTC Integration

For lower-level control, use the LiveKit SDK directly:

```javascript
import { Room, RoomEvent, Track } from 'livekit-client';

const room = new Room();

room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
  if (track.kind === Track.Kind.Audio) {
    const audioElement = track.attach();
    document.body.appendChild(audioElement);
  }
});

const response = await fetch('/api/voice-token');
const { url, token } = await response.json();

await room.connect(url, token);
await room.localParticipant.setMicrophoneEnabled(true);

// Handle data channel messages
room.on(RoomEvent.DataReceived, (payload, participant, kind, topic) => {
  if (topic === 'client_actions') {
    const data = JSON.parse(new TextDecoder().decode(payload));
    if (data.type === 'client_action') {
      console.log('Action:', data.action, data.payload);
    }
  }
});

// Send actions
room.localParticipant.publishData(
  new TextEncoder().encode(JSON.stringify({
    type: 'client_action',
    action: 'user_clicked_buy',
    payload: { productId: '123' }
  })),
  { reliable: true, topic: 'client_actions' }
);

await room.disconnect();
```

**Data Channel Protocol — all messages use topic `client_actions`:**
```json
{ "type": "client_action", "action": "action_name", "payload": { ... } }
```

**Built-in actions:**
- `heartbeat` / `heartbeat_ack` — Agent keepalive
- `send_transcript` — Transcript entry `{ role, text, timestamp }`
- `query_agent` / `agent_response` — AI Agent query/response
- `stop_talking` / `start_talking` — Mute/un-mute the agent on demand

**Dependencies:**
```bash
npm install livekit-client          # JavaScript
pip install livekit requests        # Python
# Flutter: livekit_client: ^2.3.0, http: ^1.2.0
```

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
| `heartbeat` | `{ timestamp, agent_identity }` | Agent keepalive |
| `microphoneChanged` | boolean | Mic state change |
| `error` | VocalBridgeError | Error handling |

## Error Codes

| Code | When |
|------|------|
| `TOKEN_FETCH_FAILED` | Token request failed (network, 401, etc.) |
| `CONNECTION_FAILED` | WebRTC connection failed |
| `MICROPHONE_ERROR` | Mic access denied or unavailable |
| `DATA_CHANNEL_ERROR` | Failed to send data to agent |
| `RECONNECT_FAILED` | All reconnection attempts exhausted |
| `USAGE_LIMIT_EXCEEDED` | 403 from token endpoint |
| `AGENT_NOT_FOUND` | 404 — agent ID doesn't exist |
| `AGENT_NOT_ACTIVE` | Agent exists but isn't active |

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

"""
Sabre API integration — SabreClient helper class.

Auth model: **Bearer token** (you set SABRE_ACCESS_TOKEN in .env; the hackathon
hands these out on-site). No OAuth dance needed — every request sends
    Authorization: Bearer <SABRE_ACCESS_TOKEN>

Endpoints (verified against developer.sabre.com + the SabreDevStudio Postman
collections — Flight Reshop / Booking-Management / Bargain Finder Max):

  TWO coherent real paths. Pick ONE — don't mix search from one with book from
  the other, because the object models differ.

  PATH A — simplest, self-contained (DEFAULT, what's wired):
    Search:  GET  {BASE}/v1/shop/flights            (InstaFlights)
    Book:    POST {BASE}/v2.5.0/passenger/records    (Create PNR)
    Create PNR takes explicit flight SEGMENTS, which we build straight from the
    InstaFlights result — no intermediate offer object. Chains end-to-end.

  PATH B — Orders / Booking Management (judge-aligned; more moving parts):
    Search:  POST {BASE}/v3/offers/shop              (Bargain Finder Max, offers mode)
    Book:    POST {BASE}/v1/trip/orders/createBooking (consumes the OFFER from above)
    Ticket:  POST {BASE}/v1/trip/orders/fulfillFlightTickets
    Read:    POST {BASE}/v1/trip/orders/getBooking    (confirmationId lives here)
    Here createBooking's `flightOffer` MUST come from /offers/shop — that's the
    same object model, so it fits. (This is why Create Booking can't consume an
    InstaFlights PricedItinerary — different shape.)

  On-theme bonus — Flight Reshop:
    POST {BASE}/v1/offers/flightReshop  — Sabre's real "re-shop a DISRUPTED
    ticket" API. Perfect story fit, BUT it needs an existing *ticket number*
    (a real ticketed PNR) as input, which our staged demo doesn't have. Noted
    for completeness; not used.

  NOTE on BFM versions: classic REST BFM is /v5/shop/flights and returns a
  PricedItinerary (feeds Create PNR, PATH A-style). The Orders BFM is
  /v3/offers/shop and returns OFFERS (feeds createBooking, PATH B). Same product,
  two response shapes — match the one to your booking call.

DEMO_MODE=true short-circuits every network call to realistic fake data so the
whole loop runs offline. Flip to false in .env once your token is in place.

Backwards-compatible module functions `search_flights()` / `book_flight()` are
kept at the bottom so main.py doesn't need to change.
"""
from __future__ import annotations

import os
import httpx


def _truthy(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


def _demo_mode() -> bool:
    return _truthy("DEMO_MODE", "true")


def _sabre_live() -> bool:
    """Real Sabre SEARCH calls. Decoupled from DEMO_MODE so search can be live
    while voice/Claude stay in demo. Requires SABRE_LIVE=true (+ a token)."""
    return _truthy("SABRE_LIVE", "false")


def _booking_enabled() -> bool:
    """Real BOOKING (Create PNR / ticketing). OFF by default — the demo never
    creates a real reservation. Set SABRE_BOOKING_ENABLED=true only if you truly
    intend to book in CERT."""
    return _truthy("SABRE_BOOKING_ENABLED", "false")


class SabreClient:
    """Thin wrapper over the Sabre REST APIs we need, using Bearer auth."""

    def __init__(
        self,
        access_token: str | None = None,
        base_url: str | None = None,
        pcc: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or os.getenv("SABRE_BASE_URL", "https://api.cert.platform.sabre.com")).rstrip("/")
        self.access_token = access_token or os.getenv("SABRE_ACCESS_TOKEN", "")
        self.pcc = pcc or os.getenv("SABRE_PCC", "")
        self.timeout = timeout

    # -- internals ----------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict) -> dict:
        r = httpx.get(f"{self.base_url}{path}", headers=self._headers(), params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = httpx.post(f"{self.base_url}{path}", headers=self._headers(), json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # -- 1. SEARCH (InstaFlights) ------------------------------------------
    def search_flights(self, origin: str, destination: str, depart_date: str,
                        passengers: int = 1, limit: int = 5) -> list[dict]:
        """
        InstaFlights Search — GET /v1/shop/flights. Simplest Sabre search: query
        params in, priced itineraries out. `depart_date` is YYYY-MM-DD.
        Returns our normalized flight dicts (see _normalize_instaflights).
        """
        if not _sabre_live() or not self.access_token:
            return _fake_search_results(origin, destination, depart_date)

        params = {
            "origin": origin,
            "destination": destination,
            "departuredate": depart_date,
            "limit": limit,
            "passengercount": passengers,
            "sortby": "totalfare",
            "order": "asc",
            "pointofsalecountry": "US",
        }
        try:
            data = self._get("/v1/shop/flights", params)
        except httpx.HTTPStatusError as e:
            # InstaFlights returns 404 (not empty 200) when a route/date has no
            # inventory in CERT. Treat that as "no alternatives", not an error.
            if e.response.status_code == 404:
                return []
            raise
        return self._normalize_instaflights(data, origin, destination, depart_date)

    # -- 1b. SEARCH (Bargain Finder Max v5) --------------------------------
    def search_flights_bfm(self, origin: str, destination: str, depart_date: str,
                           passengers: int = 1, limit: int = 5) -> list[dict]:
        """
        Bargain Finder Max v5 — POST /v5/shop/flights. More complete than
        InstaFlights (branded fares, richer options). Same normalized output.
        Same OTA PricedItinerary response shape, so the normalizer is shared.
        """
        if not _sabre_live() or not self.access_token:
            return _fake_search_results(origin, destination, depart_date)

        body = {
            "OTA_AirLowFareSearchRQ": {
                "Version": "5",
                "OriginDestinationInformation": [{
                    "RPH": "1",
                    "DepartureDateTime": f"{depart_date}T00:00:00",
                    "OriginLocation": {"LocationCode": origin},
                    "DestinationLocation": {"LocationCode": destination},
                }],
                "POS": {"Source": [{"PseudoCityCode": self.pcc, "RequestorID": {
                    "Type": "1", "ID": "1", "CompanyName": {"Code": "TN"}}}]},
                "TravelPreferences": {"TPA_Extensions": {"NumTrips": {"Number": limit}}},
                "TravelerInfoSummary": {
                    "SeatsRequested": [passengers],
                    "AirTravelerAvail": [{"PassengerTypeQuantity": [
                        {"Code": "ADT", "Quantity": passengers}]}],
                },
            }
        }
        data = self._post("/v5/shop/flights", body)
        return self._normalize_instaflights(data, origin, destination, depart_date)

    # -- 2. BOOK (Create PNR) ----------------------------------------------
    def create_booking(self, flight: dict, passenger: dict | None = None) -> dict:
        """
        Create Passenger Name Record — POST /v2.5.0/passenger/records.
        Builds the air segment directly from a normalized `flight` dict, so it
        chains straight off search_flights(). Returns:
            {"confirmationId": "<PNR>", "status": "CONFIRMED", "flight": flight}
        """
        passenger = passenger or {"first_name": "DEMO", "last_name": "TRAVELER"}

        # Booking is OFF by default — return a simulated confirmation, never a
        # real PNR. Real Create PNR only runs if SABRE_BOOKING_ENABLED=true.
        if not _booking_enabled():
            return {"confirmationId": _fake_pnr(flight), "status": "CONFIRMED",
                    "flight": flight, "simulated": True}

        carrier = (flight.get("carrier_code") or flight.get("flight_number", "  ")[:2])
        number = flight.get("flight_number", "")[len(carrier):]
        body = {
            "CreatePassengerNameRecordRQ": {
                "version": "2.5.0",
                "targetCity": self.pcc,
                "TravelItineraryAddInfo": {
                    "AgencyInfo": {"Address": {"CountryCode": "US"}},
                    "CustomerInfo": {"PersonName": [{
                        "NameNumber": "1.1", "PassengerType": "ADT",
                        "GivenName": passenger["first_name"], "Surname": passenger["last_name"],
                    }]},
                },
                "AirBook": {"OriginDestinationInformation": {"FlightSegment": [{
                    "DepartureDateTime": flight["depart"],
                    "ArrivalDateTime": flight["arrive"],
                    "FlightNumber": number,
                    "NumberInParty": "1",
                    "ResBookDesigCode": flight.get("booking_class", "Y"),
                    "Status": "NN",
                    "OriginLocation": {"LocationCode": flight["origin"]},
                    "DestinationLocation": {"LocationCode": flight["destination"]},
                    "MarketingAirline": {"Code": carrier},
                }]}},
                "PostProcessing": {"EndTransaction": {
                    "Source": {"ReceivedFrom": "Tailwind AI"}}},
            }
        }
        data = self._post("/v2.5.0/passenger/records", body)
        # PNR locator lives here in the Create PNR response.
        pnr = (data.get("CreatePassengerNameRecordRS", {})
                   .get("ItineraryRef", {}).get("ID")) or _fake_pnr(flight)
        return {"confirmationId": pnr, "status": "CONFIRMED", "flight": flight}

    # -- PATH B: Orders / Booking Management --------------------------------
    def create_booking_management(self, flight_offer: dict, passenger: dict) -> dict:
        """
        Booking Management Create Booking — POST /v1/trip/orders/createBooking.
        `flight_offer` MUST be an offer object from POST /v3/offers/shop (Orders
        BFM), NOT an InstaFlights PricedItinerary — same-object-model rule.
        Response confirmation is `confirmationId`. Follow with fulfill_tickets()
        to actually issue the ticket.
        """
        if not _booking_enabled():
            return {"confirmationId": _fake_pnr(flight_offer), "status": "CONFIRMED",
                    "flight": flight_offer, "simulated": True}

        body = {
            "flightOffer": flight_offer,  # TODO(on-site): the offer from /v3/offers/shop
            "profiles": [{
                "passenger": {
                    "givenName": passenger["first_name"],
                    "surname": passenger["last_name"],
                    "passengerCode": "ADT",
                }
            }],
            "receivedFrom": "Tailwind AI",
        }
        data = self._post("/v1/trip/orders/createBooking", body)
        pnr = data.get("confirmationId") or data.get("id") or _fake_pnr(flight_offer)
        return {"confirmationId": pnr, "status": "CONFIRMED", "flight": flight_offer}

    def fulfill_tickets(self, confirmation_id: str) -> dict:
        """Issue the ticket for a created booking — POST /v1/trip/orders/fulfillFlightTickets."""
        if not _booking_enabled():
            return {"confirmationId": confirmation_id, "ticketed": True, "simulated": True}
        return self._post("/v1/trip/orders/fulfillFlightTickets", {"confirmationId": confirmation_id})

    def get_booking(self, confirmation_id: str) -> dict:
        """Read a booking back — POST /v1/trip/orders/getBooking. confirmationId in the response."""
        if not _sabre_live() or not self.access_token:
            return {"confirmationId": confirmation_id, "status": "CONFIRMED"}
        return self._post("/v1/trip/orders/getBooking", {"confirmationId": confirmation_id})

    # -- normalization ------------------------------------------------------
    @staticmethod
    def _normalize_instaflights(raw: dict, origin: str, destination: str, depart_date: str) -> list[dict]:
        """
        Map Sabre's OTA PricedItinerary response (InstaFlights & BFM share it)
        into our simple flight dicts. Verified field paths:
          PricedItineraries[]
            .AirItineraryPricingInfo.ItinTotalFare.TotalFare.{Amount,CurrencyCode}
            .AirItinerary.OriginDestinationOptions.OriginDestinationOption[]
                .FlightSegment[]
                    .MarketingAirline.Code, .FlightNumber,
                    .DepartureAirport.LocationCode, .DepartureDateTime,
                    .ArrivalAirport.LocationCode, .ArrivalDateTime, .ResBookDesigCode
        Falls back to demo data if the shape isn't what we expect.
        """
        try:
            # InstaFlights: top-level "PricedItineraries" is a list.
            # BFM/SOAP sometimes nests as OTA_AirLowFareSearchRS.PricedItineraries.PricedItinerary
            itineraries = raw.get("PricedItineraries")
            if itineraries is None:
                itineraries = (raw.get("OTA_AirLowFareSearchRS", {})
                                  .get("PricedItineraries", {}).get("PricedItinerary", []))

            results = []
            for it in itineraries:
                od = it["AirItinerary"]["OriginDestinationOptions"]["OriginDestinationOption"]
                od0 = od[0] if isinstance(od, list) else od
                segs = od0["FlightSegment"]
                first, last = segs[0], segs[-1]
                fare = it["AirItineraryPricingInfo"]["ItinTotalFare"]["TotalFare"]
                carrier_code = first["MarketingAirline"]["Code"]
                results.append({
                    "flight_number": f"{carrier_code}{first['FlightNumber']}",
                    "carrier_code": carrier_code,
                    "carrier": carrier_code,
                    "origin": first["DepartureAirport"]["LocationCode"],
                    "destination": last["ArrivalAirport"]["LocationCode"],
                    "depart": first["DepartureDateTime"],
                    "arrive": last["ArrivalDateTime"],
                    "duration": "",
                    "stops": len(segs) - 1,
                    "price": float(fare["Amount"]),
                    "currency": fare["CurrencyCode"],
                    "cabin": "Economy",
                    "booking_class": first.get("ResBookDesigCode", "Y"),
                    "seats_left": None,
                })
            return results or _fake_search_results(origin, destination, depart_date)
        except (KeyError, IndexError, TypeError, ValueError):
            return _fake_search_results(origin, destination, depart_date)


# ---------------------------------------------------------------------------
# Backwards-compatible module functions (main.py calls these).
# They wrap a default SabreClient so nothing else needs to change.
# ---------------------------------------------------------------------------
_default_client = SabreClient()


def search_flights(old_flight: dict) -> list[dict]:
    """Find alternatives on the same route/date as the cancelled flight."""
    return _default_client.search_flights(
        origin=old_flight["origin"],
        destination=old_flight["destination"],
        depart_date=old_flight["depart"][:10],
    )


def book_flight(flight: dict, passenger: dict | None = None) -> dict:
    """Rebook the chosen flight. Returns {"pnr", "status", "flight"}."""
    result = _default_client.create_booking(flight, passenger)
    # keep the old "pnr" key for main.py / the frontend
    return {"pnr": result["confirmationId"], "status": result["status"], "flight": result["flight"]}


# ---------------------------------------------------------------------------
# Demo / fallback data
# ---------------------------------------------------------------------------
def _fake_search_results(origin: str, destination: str, depart_date: str) -> list[dict]:
    o, d, date = origin, destination, depart_date
    return [
        {"flight_number": "AA1245", "carrier_code": "AA", "carrier": "American Airlines",
         "origin": o, "destination": d, "depart": f"{date}T20:15:00", "arrive": f"{date}T23:05:00",
         "duration": "3h 50m", "stops": 0, "price": 214.00, "currency": "USD",
         "cabin": "Economy", "booking_class": "Y", "seats_left": 5},
        {"flight_number": "UA892", "carrier_code": "UA", "carrier": "United Airlines",
         "origin": o, "destination": d, "depart": f"{date}T21:40:00", "arrive": f"{date}T23:58:00",
         "duration": "3h 18m", "stops": 0, "price": 268.00, "currency": "USD",
         "cabin": "Economy", "booking_class": "Y", "seats_left": 12},
        {"flight_number": "WN2210", "carrier_code": "WN", "carrier": "Southwest Airlines",
         "origin": o, "destination": d, "depart": f"{date}T19:05:00", "arrive": f"{date}T23:35:00",
         "duration": "5h 30m", "stops": 1, "price": 179.00, "currency": "USD",
         "cabin": "Economy", "booking_class": "Y", "seats_left": 3},
    ]


def _fake_pnr(flight: dict) -> str:
    seed = f"{flight.get('flight_number', 'XXX')}{flight.get('depart', '')}"
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    h = abs(hash(seed))
    return "".join(alphabet[(h >> (i * 5)) % len(alphabet)] for i in range(6))

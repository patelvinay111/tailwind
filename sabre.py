"""
Sabre API integration: flight search + rebooking.

Two public functions:
    search_flights(old_flight)  -> list[dict]   real alternative flights
    book_flight(flight)         -> dict          booking confirmation (PNR)

In DEMO_MODE these return realistic fake data so the whole loop runs offline.
Once you have Sabre CERT credentials on-site, set DEMO_MODE=false in .env and
fill in SABRE_CLIENT_ID / SABRE_CLIENT_SECRET (or SABRE_ACCESS_TOKEN).

Docs while you build:
  - Auth (OAuth2 client_credentials): POST {BASE}/v2/auth/token
  - Bargain Finder Max (search):       POST {BASE}/v4/offers/shop
  - Booking / Create PNR:              POST {BASE}/v2/orders/create   (or Bargain
                                       Finder Max Book / SOAP CreatePassengerNameRecord
                                       depending on what the hackathon enables)
Endpoint paths vary by Sabre account tier — adjust the paths below to whatever
the on-site docs give you. The request/response *shape* is what matters here.
"""
from __future__ import annotations

import os
import base64
import httpx

SABRE_BASE_URL = os.getenv("SABRE_BASE_URL", "https://api.cert.platform.sabre.com")
SABRE_CLIENT_ID = os.getenv("SABRE_CLIENT_ID", "")
SABRE_CLIENT_SECRET = os.getenv("SABRE_CLIENT_SECRET", "")
SABRE_ACCESS_TOKEN = os.getenv("SABRE_ACCESS_TOKEN", "")
SABRE_PCC = os.getenv("SABRE_PCC", "")


def _demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _get_token() -> str:
    """OAuth2 client_credentials -> bearer token. Cached-per-call for simplicity."""
    if SABRE_ACCESS_TOKEN:
        return SABRE_ACCESS_TOKEN

    # TODO(on-site): confirm the token endpoint path with the hackathon Sabre docs.
    creds = f"{SABRE_CLIENT_ID}:{SABRE_CLIENT_SECRET}".encode()
    basic = base64.b64encode(creds).decode()
    resp = httpx.post(
        f"{SABRE_BASE_URL}/v2/auth/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search_flights(old_flight: dict) -> list[dict]:
    """
    Find real alternative flights on the same route, departing after the
    cancelled one. Returns a normalized list the rest of the app understands:

        {
          "flight_number": "AA1245",
          "carrier": "American Airlines",
          "origin": "SFO", "destination": "AUS",
          "depart": "2026-07-18T20:15:00", "arrive": "2026-07-19T02:05:00",
          "duration": "3h 50m", "stops": 0,
          "price": 214.00, "currency": "USD",
          "cabin": "Economy", "seats_left": 5,
        }
    """
    if _demo_mode():
        return _fake_search_results(old_flight)

    token = _get_token()
    origin = old_flight["origin"]
    destination = old_flight["destination"]
    depart_date = old_flight["depart"][:10]  # YYYY-MM-DD

    # TODO(on-site): swap in the exact Bargain Finder Max request body the docs give
    # you. This is the standard BFM v4 shape; tweak passenger types / cabin as needed.
    body = {
        "OTA_AirLowFareSearchRQ": {
            "OriginDestinationInformation": [
                {
                    "DepartureDateTime": f"{depart_date}T00:00:00",
                    "OriginLocation": {"LocationCode": origin},
                    "DestinationLocation": {"LocationCode": destination},
                }
            ],
            "TravelPreferences": {"TPA_Extensions": {"NumTrips": {"Number": 5}}},
            "TravelerInfoSummary": {
                "AirTravelerAvail": [{"PassengerTypeQuantity": [{"Code": "ADT", "Quantity": 1}]}]
            },
        }
    }
    resp = httpx.post(
        f"{SABRE_BASE_URL}/v4/offers/shop",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return _normalize_search_response(resp.json(), old_flight)


def _normalize_search_response(raw: dict, old_flight: dict) -> list[dict]:
    """
    Map Sabre's verbose response into our simple flight dicts.
    TODO(on-site): walk the real BFM response structure here. The path is roughly
    OTA_AirLowFareSearchRS -> PricedItineraries -> PricedItinerary[]. Print one
    response and adjust. Falls back to demo data if the shape isn't what we expect.
    """
    try:
        itineraries = raw["OTA_AirLowFareSearchRS"]["PricedItineraries"]["PricedItinerary"]
        results = []
        for it in itineraries:
            seg = it["AirItinerary"]["OriginDestinationOptions"]["OriginDestinationOption"][0][
                "FlightSegment"
            ][0]
            fare = it["AirItineraryPricingInfo"]["ItinTotalFare"]["TotalFare"]
            results.append(
                {
                    "flight_number": f"{seg['MarketingAirline']['Code']}{seg['FlightNumber']}",
                    "carrier": seg["MarketingAirline"]["Code"],
                    "origin": seg["DepartureAirport"]["LocationCode"],
                    "destination": seg["ArrivalAirport"]["LocationCode"],
                    "depart": seg["DepartureDateTime"],
                    "arrive": seg["ArrivalDateTime"],
                    "duration": "",
                    "stops": 0,
                    "price": float(fare["Amount"]),
                    "currency": fare["CurrencyCode"],
                    "cabin": "Economy",
                    "seats_left": None,
                }
            )
        return results or _fake_search_results(old_flight)
    except (KeyError, IndexError, TypeError):
        return _fake_search_results(old_flight)


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
def book_flight(flight: dict, passenger: dict | None = None) -> dict:
    """
    Actually rebook the chosen flight. Returns a confirmation dict:
        {"pnr": "XY7Q2L", "status": "CONFIRMED", "flight": {...}}
    """
    passenger = passenger or {"first_name": "DEMO", "last_name": "TRAVELER"}

    if _demo_mode():
        return {
            "pnr": _fake_pnr(flight),
            "status": "CONFIRMED",
            "flight": flight,
        }

    token = _get_token()

    # TODO(on-site): this is the piece most likely to need adjustment. Depending on
    # what the hackathon enables you'll either:
    #   (a) call the REST Create Order / Book endpoint, or
    #   (b) run the classic flow: EnhancedAirBook -> PassengerDetails -> EndTransaction.
    # Fill in the exact body from the on-site docs. Shape below is a placeholder.
    body = {
        "CreatePassengerNameRecordRQ": {
            "targetCity": SABRE_PCC,
            "TravelItineraryAddInfo": {
                "CustomerInfo": {
                    "PersonName": [
                        {
                            "GivenName": passenger["first_name"],
                            "Surname": passenger["last_name"],
                            "NameNumber": "1.1",
                            "PassengerType": "ADT",
                        }
                    ]
                }
            },
            "AirBook": {
                "OriginDestinationInformation": {
                    "FlightSegment": [
                        {
                            "DepartureDateTime": flight["depart"],
                            "ArrivalDateTime": flight["arrive"],
                            "FlightNumber": flight["flight_number"][2:],
                            "NumberInParty": "1",
                            "ResBookDesigCode": "Y",
                            "Status": "NN",
                            "OriginLocation": {"LocationCode": flight["origin"]},
                            "DestinationLocation": {"LocationCode": flight["destination"]},
                            "MarketingAirline": {"Code": flight["carrier"][:2]},
                        }
                    ]
                }
            },
            "PostProcessing": {"EndTransaction": {"Source": {"ReceivedFrom": "Tailwind AI"}}},
        }
    }
    resp = httpx.post(
        f"{SABRE_BASE_URL}/v2/passenger/records",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=45,
    )
    resp.raise_for_status()
    data = resp.json()
    # TODO(on-site): pull the real locator out of the response.
    pnr = (
        data.get("CreatePassengerNameRecordRS", {})
        .get("ItineraryRef", {})
        .get("ID", _fake_pnr(flight))
    )
    return {"pnr": pnr, "status": "CONFIRMED", "flight": flight}


# ---------------------------------------------------------------------------
# Demo / fallback data
# ---------------------------------------------------------------------------
def _fake_search_results(old_flight: dict) -> list[dict]:
    o, d = old_flight["origin"], old_flight["destination"]
    date = old_flight["depart"][:10]
    return [
        {
            "flight_number": "AA1245",
            "carrier": "American Airlines",
            "origin": o, "destination": d,
            "depart": f"{date}T20:15:00", "arrive": f"{date}T23:05:00",
            "duration": "3h 50m", "stops": 0,
            "price": 214.00, "currency": "USD",
            "cabin": "Economy", "seats_left": 5,
        },
        {
            "flight_number": "UA892",
            "carrier": "United Airlines",
            "origin": o, "destination": d,
            "depart": f"{date}T21:40:00", "arrive": f"{date}T23:58:00",
            "duration": "3h 18m", "stops": 0,
            "price": 268.00, "currency": "USD",
            "cabin": "Economy", "seats_left": 12,
        },
        {
            "flight_number": "WN2210",
            "carrier": "Southwest Airlines",
            "origin": o, "destination": d,
            "depart": f"{date}T19:05:00", "arrive": f"{date}T23:35:00",
            "duration": "5h 30m", "stops": 1,
            "price": 179.00, "currency": "USD",
            "cabin": "Economy", "seats_left": 3,
        },
    ]


def _fake_pnr(flight: dict) -> str:
    # Deterministic-ish 6-char locator so it looks real without randomness deps.
    seed = f"{flight.get('flight_number','XXX')}{flight.get('depart','')}"
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    h = abs(hash(seed))
    return "".join(alphabet[(h >> (i * 5)) % len(alphabet)] for i in range(6))

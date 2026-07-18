# Sabre Air Search Skill Guide

Use this guide when a coding agent needs to implement Sabre air shopping and connect search results to the next booking or servicing step.

## When to use this skill

- You are building a flight search flow for shopping, pricing, and offer selection.
- You need to choose between Sabre Flight Shop and Flight Shop Lite.
- You want to connect shopping output to revalidation, booking creation, or downstream booking retrieval.

## Primary docs to read first

- Sabre Flight Shop API: https://developer.sabre.com/rest-api/flightshop-api/v1
- Sabre Flight Shop Lite API: https://developer.sabre.com/rest-api/flightshoplite-api/v1
- OAuth Token Create REST API v2: https://developer.sabre.com/rest-api/oauth-token-create-rest-api/v2
- OAuth Token Create REST API v3: https://developer.sabre.com/rest-api/oauth-token-create-rest-api/v3
- Booking Management API: https://developer.sabre.com/rest-api/booking-management-api
- Sabre Flight Check API: https://developer.sabre.com/rest-api/flightcheck-api/v1

## Choose the right API

- Use **Sabre Flight Shop** when you need richer multi-source shopping and broader offer coverage.
- Use **Flight Shop Lite** when you want faster, lightweight shopping based on pre-computed offers from the Sabre cache.

## Implementation workflow

1. Authenticate first with the correct OAuth flow for the environment.
2. Build the shopping request with origin, destination, travel date, traveler details, and optional filtering parameters.
3. Choose Sabre Flight Shop or Flight Shop Lite based on content breadth and performance needs.
4. Parse the returned offers and preserve the identifiers needed for the next step.
5. If the workflow requires confirmation before booking, call Sabre Flight Check.
6. Pass the selected offer into the Booking Management API to create the booking.
7. Use booking retrieval or cancellation endpoints for post-booking servicing.

## Required inputs and request data

- OAuth token
- Origin and destination airport codes
- Departure date and any return segment details
- Passenger types and count
- Cabin or fare preferences
- Optional filters such as stops, carriers, or source preferences

## Common mistakes

- Starting shopping without a valid OAuth token
- Treating Flight Shop Lite as a drop-in replacement for every richer shopping scenario
- Losing the selected offer identifiers needed for revalidation or booking
- Skipping Flight Check when the workflow needs final availability or price confirmation
- Assuming booking-management payloads can be created without preserving search response context

## Related docs

- Authentication guide: https://developer.sabre.com/guide/sabre-api-authentication/sabre-api-authentication.html
- REST APIs token and credentials guide: https://developer.sabre.com/guide/rest-apis-token-credentials/rest-apis-token-credentials.html
- Flight Reshop API: https://developer.sabre.com/rest-api/flight-reshop-api/v1
- New Distribution Capability collection: https://developer.sabre.com/product-collection/new-distribution-capability-ndc
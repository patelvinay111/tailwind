# Sabre Hotel Search Skill Guide

Use this guide when a coding agent needs to implement a hotel shopping flow from availability through booking and servicing.

## When to use this skill

- You are building a lodging search and booking workflow.
- You need to chain hotel availability, hotel details, and hotel price confirmation calls.
- You need to pass hotel shopping results into the Booking Management API.

## Primary docs to read first

- Get Hotel Availability: https://developer.sabre.com/rest-api/get-hotel-avail
- Get Hotel Details: https://developer.sabre.com/rest-api/get-hotel-details
- Hotel Price Check: https://developer.sabre.com/rest-api/hotel-price-check
- Booking Management API: https://developer.sabre.com/rest-api/booking-management-api
- OAuth Token Create REST API v2: https://developer.sabre.com/rest-api/oauth-token-create-rest-api/v2
- OAuth Token Create REST API v3: https://developer.sabre.com/rest-api/oauth-token-create-rest-api/v3

## Implementation workflow

1. Authenticate before making hotel API calls.
2. Call Get Hotel Availability with destination, stay dates, guest counts, and room details.
3. Use Get Hotel Details to enrich the selected property with amenities, room, and policy data.
4. Call Hotel Price Check immediately before finalizing the booking flow.
5. Preserve the identifiers and rate information returned from the search and price-check steps.
6. Submit the selected hotel offer to the Booking Management API to create the reservation.
7. Use booking retrieval or cancellation endpoints for servicing.

## Required inputs and request data

- OAuth token
- Destination or property identifiers
- Check-in and check-out dates
- Guest count and room count
- Selected property and rate identifiers carried from previous responses
- Traveler and payment details for booking creation

## Common mistakes

- Skipping Hotel Price Check before booking
- Dropping the rate key or property identifiers between calls
- Treating hotel details data as booking-confirmation data
- Not checking cancellation or pricing rules before post-booking actions
- Mixing test and production credentials in the same workflow

## Related docs

- Authentication guide: https://developer.sabre.com/guide/sabre-api-authentication/sabre-api-authentication.html
- REST APIs token and credentials guide: https://developer.sabre.com/guide/rest-apis-token-credentials/rest-apis-token-credentials.html
- Content Services for Lodging collection: https://developer.sabre.com/product-collection/content-services-for-lodging-csl
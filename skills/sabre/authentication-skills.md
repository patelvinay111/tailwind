# Sabre Authentication Skill Guide

Use this guide when a coding agent needs to authenticate against Sabre REST APIs and prepare a working token flow before implementing any shopping or booking workflow.

## When to use this skill

- You need to generate an access token before calling a Sabre REST API.
- You need to decide whether the workflow should use OAuth v2 or OAuth v3.
- You are wiring Postman, backend code, or automation to reuse Sabre access tokens.

## Primary docs to read first

- Authentication overview: https://developer.sabre.com/guide/sabre-api-authentication/sabre-api-authentication.html
- REST APIs token and credentials guide: https://developer.sabre.com/guide/rest-apis-token-credentials/rest-apis-token-credentials.html
- OAuth Token Create REST API v2: https://developer.sabre.com/rest-api/oauth-token-create-rest-api/v2
- OAuth Token Create REST API v3: https://developer.sabre.com/rest-api/oauth-token-create-rest-api/v3
- Implementing REST OAuth Token v3: https://developer.sabre.com/blog/implementing-rest-oauth-token-v3
- Applications page for test credentials: https://developer.sabre.com/my-account/applications

## Implementation workflow

1. Confirm whether the integration is sandbox-only or production-bound.
2. Collect the required credentials from the Sabre account setup flow.
3. Use OAuth v2 for initial sandbox development unless the target workflow explicitly requires v3.
4. Use OAuth v3 for production implementations.
5. Generate a token and store its expiry metadata with the token value.
6. Send the token in the `Authorization: Bearer <token>` header on every REST API request.
7. Implement token refresh or token regeneration before expiry instead of waiting for runtime failures.

## Required inputs and credentials

- Sabre account access
- PCC
- OAuth credentials for the selected version
- Environment target: test or production
- Application code that can securely store secrets and rotate tokens

## Common mistakes

- Using OAuth v2 assumptions in a production workflow that requires OAuth v3
- Treating credentials from the Applications page as interchangeable with production credentials
- Forgetting to send the `Authorization` header on follow-on requests
- Not handling token expiration and refresh
- Hard-coding secrets in sample code or source control

## Related docs

- Sabre Flight Shop API: https://developer.sabre.com/rest-api/flightshop-api/v1
- Sabre Flight Shop Lite API: https://developer.sabre.com/rest-api/flightshoplite-api/v1
- Booking Management API: https://developer.sabre.com/rest-api/booking-management-api
- Hotel Price Check: https://developer.sabre.com/rest-api/hotel-price-check
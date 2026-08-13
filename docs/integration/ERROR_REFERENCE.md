# Error Reference

> Every error response from the integration surface, its meaning, and the
> recommended client behavior. Reflects the **current implemented backend** ✅.

## Format

All errors are FastAPI-standard JSON:
```json
{ "detail": "<message>" }
```
HTTP `422` validation errors (malformed/﻿missing body fields) use FastAPI's
structured form:
```json
{ "detail": [ { "loc": ["body", "quantity"], "msg": "…", "type": "…" } ] }
```

**Under `/yourapp/*` only**, every error body additionally carries
`"status": false` (and every success carries `"status": true`), so YourApp can
branch on the flag instead of the HTTP code:
```json
{ "detail": "Invalid code", "status": false }
```
The HTTP code is unchanged, and so are the headers (a `429` keeps its
`Retry-After`). This is stamped by four exception handlers rather than inside
the endpoints, so it also covers failures raised before the endpoint runs —
auth, rate limiting, request validation — plus unhandled crashes, which answer
`500 { "detail": "Internal server error", "status": false }` instead of a dead
connection. Nothing outside `/yourapp/*` is affected. See
[API_REFERENCE](API_REFERENCE.md#the-status-flag-yourapp-only).

## Status codes at a glance

| HTTP | Class | Retryable? | General client behavior |
|---|---|---|---|
| `400` | Bad request (semantic) | No | Fix the reference/input. |
| `401` | Unauthenticated | After re-exchange | Re-mint assertion → retry once → else login. |
| `403` | Forbidden / not provisioned / wrong tenant | No | Show "not set up / not allowed". |
| `404` | Not found / invalid code | No | Show specific message; for `/scan` it's a normal state. |
| `409` | Conflict (state/business rule) | No (refresh) | Show the state; refresh the view. |
| `422` | Validation | No | Fix input; field-level feedback. |
| `429` | Rate limited | Yes (backoff) | Exponential backoff + jitter. |
| `502` | Vastra product service unavailable | No (server/config) | Show "catalog unavailable, try again shortly"; alert DevOps if persistent. |
| `503` | Feature not configured (SSO / YourApp key) | No (server) | "Service unavailable"; alert DevOps. |
| `5xx` | Server error | GET: yes; writes: verify first | Backoff for GETs; verify state for writes. |

## SSO & auth

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 401 | `Invalid SSO assertion` | Bad signature, wrong alg, bad `aud`/`iss`/`role`, malformed JWT | Re-mint a fresh assertion, retry once. Persisting → secret/issuer/audience mismatch (config). |
| 401 | `SSO assertion expired` | `iat` older than `SSO_MAX_AGE`, or `exp` passed | Mint fresh (check device/server clock skew); retry. |
| 401 | `Assertion missing manufacturer_external_id` | Retailer assertion lacks the claim | Fix the parent token. Not retryable as-is. |
| 403 | `Manufacturer not provisioned` | Unknown manufacturer `external_id` | Provision the manufacturer in loyalty first. |
| 403 | `Retailer not provisioned` | Unknown retailer, or `external_id` under the wrong manufacturer (cross-tenant) | Provision the retailer with `external_id` under the correct manufacturer. |
| 503 | `SSO is not configured` | `SSO_SECRET` unset on the server | Server config; contact DevOps. |
| 401 | `Invalid username or password` | Password login failure | Show login error (password flows only). |
| 401 | `Invalid or expired token` | Token no longer in the DB — logged out, **or superseded by a newer login** (single active session), or the account was blocked | Route to login / re-exchange a fresh SSO assertion. |
| 403 | `Account is blocked` | Emergency lockout (`blocked = 1`) — refused at login **and** on every request with an existing token | Show "account disabled, contact support". Not client-fixable; an admin clears the flag. |
| 401 | `Current password is incorrect` | `POST /retailer/password` | Re-prompt. |
| 422 | `New password must differ from the current one` | password change | Re-prompt. |
| 403 | `<Vastra's message>` | `POST /auth/vastra/send-otp` — Vastra refused the number (not eligible for loyalty login) | Show Vastra's message verbatim. |
| 401 | `<Vastra's message>` | `POST /auth/vastra/verify-otp` — bad/expired OTP | Re-prompt; offer resend (`is_resend: 1`). |
| 502 | `Vastra login service unavailable: <detail>` | OTP endpoints couldn't reach Vastra, or `VASTRA_API_BASE_URL` unset | Show "login via Vastra unavailable"; offer password login. |

## Vastra product catalog

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 422 | `CSV is missing a product name column (…) and a product code column (…)` | `POST /catalog/products/import` got a file without a usable name/code header | Show the accepted spellings; the file was rejected whole, nothing was written. |
| 404 | `Product not found` | `DELETE /catalog/products/{external_id}` for an unknown code, a sample, or another manufacturer's product | Refresh the list. |

> The old catalog errors (`502 Vastra product service unavailable`, `409 No
> Vastra session`, `502 Vastra rejected the product request`) **no longer
> exist** — the catalog is CSV-imported and never calls Vastra. The `502
> Vastra login service unavailable: <detail>` below is a *login* error and is
> still live.

## QR generation & batches

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 404 | `Product not found` | Legacy `{product_id}` body (panel-generated-batch path, `/web/generate` only) refers to a product missing or belonging to another manufacturer | Re-select a valid product. Does not apply to the primary `product_external_id` contract, which never looks up a local product. |
| 404 | `Batch not found` | Unknown batch, or not owned by caller | Refresh batch list. |
| 404 | `Code not found` | `GET /qr/codes/{token}/image` for unknown token | Show placeholder. |
| 422 | (validation) | `quantity` out of 1–10000, `items_per_box` out of 2–1000, etc. | Fix inputs. |

## Scan & redemption

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 404 | `Invalid code` | Unknown code **or** belongs to another manufacturer (intentionally identical — anti-enumeration) | "This code isn't valid." Normal UX state, not retryable. |
| 409 | `Code already redeemed` | A plain code was already used | "Already used." Not retryable. |
| 409 | `Box already redeemed` | A box (parent) code has no unredeemed children left | "Already used." Not retryable. |
| 401 | (auth) | Token missing/invalid | Re-exchange → retry once. |
| 429 | (rate) | Scan rate limit (default 60/min) | Back off. |

> There is **no "expired code" error** — QR codes never expire. Only the scheme
> *bonus* is time-bounded (it silently contributes 0 when no scheme is active).

### YourApp server-to-server (`POST /yourapp/qr/lookup`, `POST /yourapp/scan`, `POST /yourapp/points`)

Every row below also carries `"status": false`. Note that an **already-redeemed
code is not an error on the lookup endpoint** — it answers `200` with
`status: true` and `qrStatus: "redeemed"`.

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 503 | `YourApp integration is not configured` | `YOURAPP_API_KEY` unset on the server | Server config; contact DevOps. |
| 401 | `Invalid API key` | `X-API-Key` header missing or wrong | Fix the shared secret (config); do not retry as-is. |
| 422 | `Invalid phone number` | Fewer than 10 digits after normalization | Send the retailer's full 10-digit number. |
| 403 | `Phone number not registered` | No retailer of the scanned code's manufacturer has this phone | Onboard the retailer (CSV import with phone) under the right manufacturer. |
| 403 | `Account is blocked` | Retailer emergency lockout (`blocked = 1`) | "Account disabled, contact support." |
| 409 | `Multiple retailers share this phone number` | Duplicate normalized phone within the manufacturer — on `/yourapp/points` (which has no code, so no tenant) duplicates are counted across **all** manufacturers | Data cleanup: fix the duplicate phones in the Customers tab. |
| 404 / 409 | as `/scan` above | Same redemption core — invalid code, already redeemed | Same as `/scan`. |
| 500 | `Internal server error` | Unhandled server exception, returned with `status: false` rather than a dropped connection | Show "try again"; alert us if it persists. |

### Scan reversal (`GET /scans/lookup`, `POST /scans/reverse` — manufacturer)

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 404 | `Invalid code` | Unknown code **or** another manufacturer's (same anti-enumeration 404 as `/scan`) | "Code not found." |
| 409 | `Code is not redeemed` | Reversing a code with no active scan credit (never scanned, or already reversed and not rescanned) | Refresh via lookup. |
| 409 | `Scan already reversed` | A concurrent reversal won the race | Refresh; nothing to do. |
| 409 | `Retailer's balance is below the scanned points; reject their pending gift claims first` | Deduction would push the wallet negative (not allowed) | Reject the retailer's pending gift claims (refunds restore balance), then reverse. |

## Wallet, rewards & claims

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 404 | `Gift not available` | Gift missing/inactive | Refresh shop. |
| 403 | `Gift belongs to another manufacturer` | Cross-tenant gift | Refresh shop. |
| 409 | `Not enough points` | Balance < gift cost | Keep user on gift; show balance. |
| 404 | `Claim not found` | Unknown/again not owned | Refresh claims. |
| 409 | `Claim already <status>` | Approve/reject on a decided claim | Refresh the inbox. |

## Manufacturer catalog/management

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 409 | `Username already taken` | `POST /admin/manufacturers` | Pick another username. |
| 409 | `external_id already in use` | `POST /retailers` duplicate per manufacturer | Use a unique `external_id`. |
| 404 | `Retailer not found` | Unknown/again not owned | Refresh. |
| 400 | `Distributor not found` | `distributor_id` not owned by caller | Fix the reference. |
| 404 | `Distributor not found` | Update/delete unknown distributor | Refresh. |
| 422 | `points must be non-zero` | `/retailers/{id}/adjust` | Fix input. |
| 409 | `Adjustment would make the wallet negative` | adjust below 0 | Reduce the deduction. |
| 422 | `Cannot transfer to the same retailer` | `/retailers/transfer` | Fix input. |
| 404 | `Both retailers must belong to you` | transfer across tenants | Fix input. |
| 409 | `Sender has insufficient points` | transfer > balance | Reduce amount. |
| 422 | `end_date must be on or after start_date` | `POST /schemes` | Fix dates. |
| 404 | `One or more product_ids not found` | scheme scope (current model) | Fix selection. |
| 404 | `Gift not found` / 422 `Nothing to update` | gift update/delete | Refresh / include fields. |
| 422 | `CSV must have a '<col>' column` | imports | Fix the CSV header. |

## Rate limiting (429)

Per-endpoint buckets (env-overridable; keyed by bearer token when present, else
IP). Defaults: login/SSO `10/min`, scan `60/min`, claim `20/min`, QR generate
`30/min`, imports `10/hour`. On `429`, back off exponentially with jitter. In
multi-process deployments the limiter needs a shared store
(`RL_STORAGE_URI`) — see [DEPLOYMENT_GUIDE](DEPLOYMENT_GUIDE.md).

## Golden rules

- **Never blind-retry `/scan` or `/retailer/claim`** on ambiguous failures —
  verify state first (they change balances).
- **`401` → one-shot re-exchange + single retry**, then send to login (avoid loops).
- **`403`/`404`/`409` are not retryable** — they're business/state outcomes;
  surface a clear message and refresh the relevant view.

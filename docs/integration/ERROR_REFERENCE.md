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
| `503` | SSO not configured | No (server) | "Service unavailable"; alert DevOps. |
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
| 401 | `Current password is incorrect` | `POST /retailer/password` | Re-prompt. |
| 422 | `New password must differ from the current one` | password change | Re-prompt. |

## Vastra product catalog

| HTTP | `detail` | Meaning | Client behavior |
|---|---|---|---|
| 502 | `Vastra product service unavailable: <detail>` | `GET /vastra/products` couldn't reach Vastra, or `VASTRA_API_BASE_URL` is unset | Show "catalog unavailable"; retry with backoff. |

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

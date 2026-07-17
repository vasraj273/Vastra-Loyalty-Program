# API Reference

> Reflects the **current implemented backend** ✅, including the Product
> System-of-Record migration (`product_external_id` + snapshots) — now live as a
> dual-contract `/qr/generate` (new primary + legacy `product_id` fallback),
> and the **pull-based Vastra product catalog** (`GET /vastra/products`,
> proxied server-side) that powers QR generation from the admin panel.
> Product CRUD/import (`POST`/`PATCH`/`DELETE /products`, `POST
> /products/import`) has been **removed**. See
> [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md).
> Authoritative machine-readable schema: `/openapi.json` (Swagger UI at `/docs`).

## Conventions

- **Base URL:** the deployed origin, e.g. `https://loyalty.<host>`.
- **Auth header:** `Authorization: Bearer <loyalty token>`. A `?token=` query
  param is also accepted (used only for the print-PDF link; do not use it for
  normal app traffic — it leaks into logs).
- **Content type:** `application/json` for all request bodies (no multipart;
  CSV imports send the CSV as a JSON string).
- **Auth roles:** `None` (assertion is the credential) · `M` = manufacturer
  token · `R` = retailer token · `Admin` = super-admin token.
- All error bodies are FastAPI standard: `{ "detail": "<message>" }`. See
  [ERROR_REFERENCE](ERROR_REFERENCE.md).

## Endpoint index

| Area | Method & Route | Auth |
|---|---|---|
| SSO | `POST /auth/sso/manufacturer` | None |
| SSO | `POST /auth/sso/retailer` | None |
| Auth | `POST /auth/login` | None |
| Auth | `POST /auth/logout` | M/Admin |
| Auth | `GET /auth/me` | M/Admin |
| Auth | `POST /auth/retailer/login` | None |
| Auth | `POST /auth/retailer/logout` | R |
| Auth | `GET /retailer/me` | R |
| Provisioning | `POST /admin/manufacturers` | Admin |
| Provisioning | `POST /retailers` | M |
| Provisioning | `POST /retailers/import` | M |
| Catalog | `GET /vastra/products` | M |
| Catalog | `PUT /vastra/products/{external_id}/points` | M |
| QR | `POST /qr/generate` | M |
| QR | `POST /qr/batches/{id}/save` | M |
| QR | `GET /qr/batches` | M |
| QR | `GET /qr/batches/{id}` | M |
| QR | `GET /qr/batches/{id}/print` | M |
| QR | `DELETE /qr/batches/{id}` | M |
| QR | `GET /qr/codes/{token}/image` | None |
| Scan | `POST /scan` | R |
| Wallet | `GET /retailer/wallet` | R |
| Rewards | `GET /retailer/shop` | R |
| Rewards | `POST /retailer/claim` | R |
| Claims | `GET /retailer/claims` | R |
| Claims | `GET /gift-claims` | M |
| Claims | `POST /gift-claims/{id}/approve` | M |
| Claims | `POST /gift-claims/{id}/reject` | M |
| Catalog | `GET /claims` | M |
| Catalog | `GET /scans/lookup` · `POST /scans/reverse` | M |
| Catalog | `GET /gifts` · `POST /gifts` · `PATCH /gifts/{id}` | M |
| Catalog | `GET /schemes` · `POST /schemes` | M |
| Analytics | `GET /analytics/dashboard` | M |
| Location | `POST /retailer/location` | R |

> Other manufacturer-management endpoints (distributors, list retailers,
> adjust/transfer, `GET /products` legacy read, etc.) exist and are visible
> at `/docs`. Products CRUD (`POST`/`PATCH`/`DELETE /products`, `POST
> /products/import`) has been **removed** — the catalog is Vastra's, pulled
> via `GET /vastra/products` below. See
> [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md).

---

## SSO

### POST /auth/sso/manufacturer
- **Purpose:** exchange a Vastra-signed assertion for a loyalty manufacturer token.
- **Auth:** None. **Rate limit:** login bucket (default `10/minute` per IP).
- **Headers:** `Content-Type: application/json`.
- **Request:** `{ "assertion": "<HS256 JWT>" }`
- **Response 200:** `{ "token": "…", "display_name": "Acme Textiles", "username": "acme", "is_admin": false }`
- **Errors:** `401` invalid/expired assertion · `403` Manufacturer not provisioned · `503` SSO not configured · `429`.

### POST /auth/sso/retailer
- **Purpose:** exchange a YourApp-signed assertion for a loyalty retailer token.
- **Auth:** None. **Rate limit:** login bucket.
- **Request:** `{ "assertion": "<HS256 JWT>" }` (JWT must include `manufacturer_external_id`).
- **Response 200:** `{ "token": "…", "retailer_id": 12, "shop_name": "Kumar Cloth", "name": "Kumar", "region": "Jaipur", "manufacturer": "Acme Textiles" }`
- **Errors:** `401` invalid/expired/missing `manufacturer_external_id` · `403` Retailer not provisioned (incl. cross-tenant) · `503` · `429`.

Assertion format: see [SSO_INTEGRATION §4](SSO_INTEGRATION.md#4-jwt-assertion-format).

---

## Auth (password + identity)

### POST /auth/login
Manufacturer/super-admin password login (web panel; not used by native SSO apps).
- **Request:** `{ "username": "acme", "password": "•••" }`
- **Response 200:** `{ "token": "…", "display_name": "…", "username": "…", "is_admin": false }`
- **Errors:** `401 Invalid username or password` · `403 Account is blocked` (emergency lockout) · `429`.
- **Single active session:** a successful login invalidates this account's previous token (any prior device/session gets `401` on its next call).

### POST /auth/logout — Auth M/Admin
- **Request:** none. **Response 200:** `{ "ok": true }` (deletes the bearer token).

### GET /auth/me — Auth M/Admin
- **Response 200:** `{ "id": 1, "username": "acme", "display_name": "Acme Textiles", "is_admin": false }`
- **Errors:** `401`.

### POST /auth/retailer/login — None
Password login for retailers (dev/test; production retailer access is SSO-only).
- **Request:** `{ "username": "kumar", "password": "•••" }`
- **Response 200:** `{ "token": "…", "retailer_id": 12, "shop_name": "…", "name": "…", "region": "…", "manufacturer": "…", "must_change": false }`
- **Errors:** `401` · `403 Account is blocked` (emergency lockout) · `429`.
- **Single active session:** as with manufacturer login, a new login invalidates the retailer's previous token.

### POST /auth/retailer/logout — Auth R
- **Response 200:** `{ "ok": true }`.

### GET /retailer/me — Auth R
- **Response 200:** `{ "retailer_id": 12, "shop_name": "…", "name": "…", "region": "Jaipur", "manufacturer": "Acme Textiles", "location_source": "gps", "balance": 480, "must_change": false }`
- **Errors:** `401`.

---

## Provisioning

### POST /admin/manufacturers — Auth Admin → 201
- **Purpose:** create a manufacturer account (set `external_id` for SSO).
- **Request:** `{ "username": "acme", "password": "secret123", "display_name": "Acme Textiles" }`
  > Note: an `external_id` column exists on the table; confirm with the backend
  > team how it is populated at import time (see [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md) / [DEPLOYMENT_GUIDE](DEPLOYMENT_GUIDE.md)).
- **Response 201:** `{ "id": 4, "username": "acme", "display_name": "Acme Textiles", "created_at": "…" }`
- **Errors:** `409 Username already taken` · `401/403`.

### POST /retailers — Auth M → 201
- **Purpose:** provision a retailer (and its `external_id`) under the calling manufacturer.
- **Request:** `{ "name": "Kumar", "shop_name": "Kumar Cloth", "region": "Jaipur", "phone": "+91…", "distributor_id": null, "external_id": "YA-100" }` (`region`, `phone`, `distributor_id`, `lat`, `lng`, `external_id` optional)
- **Response 201:** the retailer row + one-time `login_username`/`login_password` (treat as a secret; for dev/test logins).
- **Errors:** `409 external_id already in use` · `400 Distributor not found` · `401/403`.

### POST /retailers/import — Auth M
- **Purpose:** bulk-provision retailers from CSV text.
- **Request:** `{ "csv": "shop_name,name,region,phone,distributor,external_id\n…" }` (`shop_name` required; `external_id` optional, unique per manufacturer).
- **Response 200:** `{ "created": 12, "skipped": 1, "errors": [...], "credentials": [{ "shop_name": "…", "username": "…", "password": "…" }] }`
- **Errors:** `422 CSV must have a 'shop_name' column` · `429`.

---

## Vastra product catalog (manufacturer side)

### GET /vastra/products — Auth M
- **Purpose:** the admin panel's product picker. Proxies Vastra's
  product-list API server-side (`app/vastra_client.py`) and merges in each
  product's stored points override. The panel never calls Vastra directly.
- **Response 200:** `[{ "external_id": "VP-1", "name": "Silk Saree", "sku": "SS-001", "points": 50 }]`
- **Errors:** `502 Vastra product service unavailable: <detail>` (Vastra
  unreachable, or `VASTRA_API_BASE_URL` unset) · `401`.

### PUT /vastra/products/{external_id}/points — Auth M
- **Purpose:** set/update the manufacturer's own points-per-scan value for a
  Vastra-catalog product (upsert into `product_points`).
- **Request:** `{ "points": 50 }`
- **Response 200:** `{ "external_id": "VP-1", "points": 50 }`
- **Errors:** `401`.

---

## QR generation & batches

### POST /qr/generate — Auth M → 201
- **Purpose:** generate a batch of QR codes for a product. **Rate limit:** `RL_QRGEN` (default `30/minute`).
- **Request (new, primary — used by the panel; product picked via `GET /vastra/products` above):**
```json
{ "product_external_id": "VP-9281", "product_name": "Silk Saree",
  "product_sku": "SS-001", "points_per_code": 50,
  "quantity": 100, "items_per_box": 10 }
```
With `product_external_id`, the fields `product_name`, `product_sku`, and
`points_per_code` are **required**; loyalty stores the snapshot and does **no**
products lookup. `quantity` 1–10000, `items_per_box` optional 2–1000 (box mode).
- **Request (legacy/transitional — panel & `/web/generate`):**
```json
{ "product_id": 3, "quantity": 100, "points_per_code": 50, "items_per_box": 10 }
```
`product_id` is looked up once to build the same snapshot; `points_per_code`
optional (defaults to the product's points). Provide **either**
`product_external_id` **or** `product_id`.
- **Response 201:**
```json
{
  "batch_id": 7, "product_id": null, "product_external_id": "VP-9281",
  "product_name": "Silk Saree", "product_sku": "SS-001",
  "quantity": 100, "points_per_code": 50, "items_per_box": 10, "boxes": 10,
  "status": "pending",
  "codes": [{ "token": "a1b2…", "manual_code": "K7M2QA", "payload": "https://host/web/scan/a1b2…" }],
  "boxes_codes": [{ "token": "…", "manual_code": "…", "payload": "…", "items": 10 }],
  "actions": { "save": "/qr/batches/7/save", "print": "/qr/batches/7/print", "discard": "/qr/batches/7" }
}
```
(`product_id` is the legacy loyalty id, `null` for the new contract.)
- **Errors:** `422` (missing snapshot fields with `product_external_id`, or
  neither id supplied, or bounds) · `404 Product not found` (legacy `product_id`
  only) · `401/403` · `429`.

### POST /qr/batches/{id}/save — Auth M
Marks a `pending` batch as `saved`. **Response 200:** `{ "batch_id": 7, "status": "saved" }`. **Errors:** `404 Batch not found`.

### GET /qr/batches — Auth M
Optional `?status=pending|saved`. **Response 200:** array of batch summaries (`batch_id`, `product_name`, `sku`, `quantity`, `points_per_code`, `status`, `created_at`).

### GET /qr/batches/{id} — Auth M
**Response 200:** batch + `codes: [{ token, manual_code, redeemed_at, redeemed_by }]`. **Errors:** `404 Batch not found`.

### GET /qr/batches/{id}/print — Auth M
- **Purpose:** printable A4 PDF of all stickers in the batch.
- **Response 200:** `application/pdf` (binary; `Content-Disposition: inline`). Accepts `?token=` so it can open in a browser tab.
- **Errors:** `404 Batch not found`.

### DELETE /qr/batches/{id} — Auth M → 204
Discards a batch and its codes. **Errors:** `404 Batch not found`.

### GET /qr/codes/{token}/image — Auth None
- **Purpose:** PNG image of a single QR code (tokens are unguessable `uuid4`).
- **Response 200:** `image/png` (binary). **Errors:** `404 Code not found`.

---

## Scan & redeem

### POST /scan — Auth R
- **Purpose:** redeem a QR (token or 6-char manual code); credits the
  **authenticated** retailer. **Rate limit:** `RL_SCAN` (default `60/minute`).
- **Request:** `{ "code": "a1b2c3…", "lat": 26.91, "lng": 75.78 }` (`code` = QR token or manual code, dashes/spaces tolerated; `lat`/`lng` optional).
- **Response 200:**
```json
{
  "redeemed": true, "is_box": false, "items_registered": 1,
  "product": { "id": null, "external_id": "VP-9281", "name": "Silk Saree", "sku": "SS-001" },
  "points_awarded": 75, "base_points": 50, "bonus_points": 25,
  "scheme": { "id": 2, "name": "Diwali Bonus" },
  "retailer": { "id": 12, "shop_name": "Kumar Cloth", "region": "Jaipur" },
  "new_balance": 555
}
```
`scheme` is `null` when no active scheme applies. For a box (parent) code,
`is_box: true` and `items_registered` = number of child codes credited.
- **Errors:** `404 Invalid code` (unknown **or** cross-manufacturer — intentionally identical) · `409 Code already redeemed` / `Box already redeemed` · `401` · `429`. See [QR_WORKFLOW](QR_WORKFLOW.md).

---

## Wallet & rewards

### GET /retailer/wallet — Auth R
- **Response 200:** `{ "retailer_id": 12, "shop_name": "…", "region": "…", "balance": 555, "history": [ { "points": 75, "base_points": 50, "bonus_points": 25, "scanned_at": "…", "entry_type": "scan", "note": null, "product_name": "Silk Saree", "sku": "SS-001", "scheme_name": "Diwali Bonus" } ] }`
- `entry_type` values: `scan`, `gift_redeem`, `refund`, `adjustment`, `transfer`, and (scan reversal) `scan_reversed` (+N, the undone scan) with its paired `reversal` (−N, `note` set) — the pair nets to zero.
- History is the latest 100 entries (all ledger types).

### GET /retailer/shop — Auth R
- **Response 200:** `{ "retailer_id": 12, "shop_name": "…", "balance": 555, "gifts": [ { "id": 1, "name": "Branded Umbrella", "description": "…", "points_cost": 300, "image_url": "…", "affordable": true } ] }`

### POST /retailer/claim — Auth R → 201
- **Purpose:** claim a gift; debits points immediately (refunded if rejected). **Rate limit:** `RL_CLAIM` (default `20/minute`).
- **Request:** `{ "gift_id": 1 }`
- **Response 201:** `{ "claim_id": 5, "reference": "RDM-7K2QABC", "gift": "Branded Umbrella", "points_spent": 300, "status": "pending", "new_balance": 255 }`
- **Errors:** `404 Gift not available` · `403 Gift belongs to another manufacturer` · `409 Not enough points` · `429`.

### GET /retailer/claims — Auth R
- **Response 200:** array of `{ id, reference, points_spent, status, created_at, decided_at, gift_name, image_url, description }`.

---

## Claims (manufacturer side)

### GET /gift-claims — Auth M
Optional `?status=pending|approved|rejected`. **Response 200:** array of `{ id, reference, points_spent, status, created_at, decided_at, gift_name, retailer_id, shop_name, retailer_name, region }`.

### POST /gift-claims/{id}/approve — Auth M
**Response 200:** `{ "claim_id": 5, "status": "approved" }`. **Errors:** `404 Claim not found` · `409 Claim already <status>`.

### POST /gift-claims/{id}/reject — Auth M
Refunds the points. **Response 200:** `{ "claim_id": 5, "status": "rejected", "refunded": 300 }`. **Errors:** `404` · `409`.

### GET /claims — Auth M
- **Purpose:** scan history (box scans collapsed to one row). Filters: `product_id` (legacy), `product_external_id`, `retailer_id`, `region`, `scheme_id`, `from`, `to`, `limit` (1–500, default 50), `offset`.
- **Response 200:** `{ "total": 214, "limit": 50, "offset": 0, "claims": [ { "id", "scanned_at", "item_count", "points", "base_points", "bonus_points", "region", "parent_token", "token", "product_id", "product_external_id", "product_name", "sku", "retailer_id", "retailer_name", "shop_name", "lat", "lng", "scheme_id", "scheme_name" } ] }`

### GET /scans/lookup — Auth M
- **Purpose:** find who redeemed a code before reversing it. `?code=` accepts the full QR token or the 6-char manual code; a child code redeemed via its box resolves to the whole box.
- **Response 200 (redeemed):** `{ "redeemed": true, "reversible": true, "reason": null, "token", "manual_code", "is_box", "item_count", "product_name", "sku", "points_per_code", "scanned_at", "points", "base_points", "bonus_points", "scheme_name", "retailer": { "id", "name", "shop_name" }, "retailer_balance" }` — `reversible: false` + `reason` when the wallet can't cover the deduction or no active scan credit exists.
- **Response 200 (unredeemed):** `{ "redeemed": false, "reversible": false, "reason": "Code has not been scanned yet", … }`
- **Errors:** `404 Invalid code` (unknown or another manufacturer's — indistinguishable).

### POST /scans/reverse — Auth M
- **Purpose:** undo a scan credited to the wrong retailer: deducts exactly the credited points (base + bonus at scan time) via negative `reversal` ledger rows, flips the originals to `scan_reversed`, and re-enables the code(s) (box scans reverse whole) so the rightful retailer can rescan.
- **Request:** `{ "code": "<token or manual code>", "note": "optional, ≤300" }`
- **Response 200:** `{ "reversed": true, "is_box", "items", "points_deducted", "retailer_id", "new_balance", "token" }`
- **Errors:** `404 Invalid code` · `409 Code is not redeemed` · `409 Scan already reversed` · `409 Retailer's balance is below the scanned points…` (no negative balances).

---

## Catalog (manufacturer side)

### GET /gifts · POST /gifts → 201 · PATCH /gifts/{id} — Auth M
- **POST request:** `{ "name": "Branded Umbrella", "description": "…", "points_cost": 300, "image_url": "…" }`
- **Response:** the gift row (`GET` adds a `claims` count). **Errors:** `404 Gift not found` · `422 Nothing to update`.

### GET /schemes · POST /schemes → 201 — Auth M
- **GET:** optional `?status=active|upcoming|previous`; returns schemes with `products` (scope), `all_products`, computed `status`.
- **POST request:** `{ "name": "Diwali Bonus", "description": "…", "start_date": "2026-10-01", "end_date": "2026-10-31", "bonus_points": 25, "product_ids": [3, 4] }` (`product_ids` empty = all products).
- **Errors:** `422 end_date must be on or after start_date` · `404 One or more product_ids not found`.

---

## Analytics

### GET /analytics/dashboard — Auth M
- **Response 200:** `{ "totals": { "retailers", "products", "scans", "points_awarded", "codes_issued", "redeem_total", "redeem_pending", "redeem_approved" }, "by_region": [...], "by_product": [...], "by_distributor": [...], "top_retailers": [...], "map_points": [...], "by_month": [ { "month": "2026-06", "generated": 500, "scanned": 120 } ] }`
- All values manufacturer-scoped. `by_month` buckets are `YYYY-MM`.

---

## Location

### POST /retailer/location — Auth R
- **Purpose:** refresh the shop's pin/city/address from the latest scan GPS (latest wins).
- **Request:** `{ "lat": 26.9124, "lng": 75.7873 }`
- **Response 200:** `{ "updated": true, "region": "Jaipur", "address": "…" }`

### GET /public/cities — Auth None
- **Response 200:** array of known place names (for an autocomplete).

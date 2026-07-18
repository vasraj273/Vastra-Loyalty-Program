# Loyalty Scan API — handoff for the YourApp team

Two server-to-server endpoints for scanning loyalty QR codes from YourApp.
Call them from the **YourApp backend only** — the API key must never ship
inside the mobile app.

- **Base URL:** `https://vastra-loyalty.onrender.com`
- **Headers (both endpoints):**
  - `Content-Type: application/json`
  - `X-API-Key: <shared secret>` — we share this privately (not in this doc)
- **All bodies and responses are JSON.** Errors look like
  `{ "detail": "<message>" }`.

---

## 1. Preview a code (optional, before redeeming)

`POST /yourapp/qr/lookup`

Shows what a code is worth and whether it was already scanned. Read-only —
calling it never redeems anything, so it is safe to call every time the
camera reads a QR.

Request:
```json
{ "code": "3f9c2a…" }
```
`code` = the token from the QR URL (`…/web/scan/<token>`) **or** the 6-char
manual code printed under it (dashes/spaces/case don't matter).

Response `200`:
```json
{
  "status": "available",
  "is_box": false,
  "items": 1,
  "product": { "external_id": "VP-9281", "name": "Silk Saree", "sku": "SS-001" },
  "base_points": 50,
  "bonus_points": 25,
  "total_points": 75,
  "scheme": { "id": 2, "name": "Diwali Bonus" },
  "redeemed_at": null,
  "redeemed_by_shop": null
}
```
- `status` becomes `"redeemed"` once scanned; then `redeemed_at` and
  `redeemed_by_shop` are filled.
- Points are **per item**. For a box sticker (`is_box: true`), each of the
  `items` children credits `total_points` (so a 12-item box = 12 ×
  `total_points`).
- `bonus_points` shows the bonus active *right now*; the final bonus is
  decided at scan time.

## 2. Redeem a scan

`POST /yourapp/scan`

Request:
```json
{
  "phone": "+91 98765 43210",
  "code": "3f9c2a…",
  "lat": 26.9124,
  "lng": 75.7873
}
```
- `phone` — the retailer's registered YourApp mobile number. We match on the
  **last 10 digits**, so `+91`, leading `0`, spaces, and dashes are all fine.
- `lat` / `lng` — optional, separate decimal fields (GPS of the scan). Send
  them when available; they power the manufacturer's scan map and keep the
  shop's pin/address current.

Response `200`:
```json
{
  "redeemed": true,
  "is_box": false,
  "items_registered": 1,
  "product": { "id": null, "external_id": "VP-9281", "name": "Silk Saree", "sku": "SS-001" },
  "points_awarded": 75,
  "base_points": 50,
  "bonus_points": 25,
  "scheme": { "id": 2, "name": "Diwali Bonus" },
  "retailer": { "id": 12, "shop_name": "Kumar Sarees", "region": "Jaipur" },
  "new_balance": 555
}
```
For a box, `items_registered` = number of items credited and the points
fields are the totals across them.

## 3. Errors to handle

| HTTP | `detail` | Meaning / what to show |
|---|---|---|
| 404 | `Invalid code` | Code doesn't exist (or belongs to another brand). "This code isn't valid." |
| 409 | `Code already redeemed` / `Box already redeemed` | Already scanned. Normal state — show who/when via the lookup endpoint if needed. |
| 403 | `Phone number not registered` | This phone isn't onboarded under the code's manufacturer. "Shop not set up for rewards — contact the manufacturer." |
| 403 | `Account is blocked` | Retailer disabled by admin. |
| 409 | `Multiple retailers share this phone number` | Data problem on our side — report it to us. |
| 422 | `Invalid phone number` | Fewer than 10 digits after cleanup. |
| 401 | `Invalid API key` | Wrong/missing `X-API-Key` — config issue, don't retry. |
| 503 | `YourApp integration is not configured` | Key not set on our server — contact us. |
| 429 | (rate limited) | Back off and retry after a moment. |

Notes:
- **Don't blind-retry the scan call** on a timeout — check with
  `/yourapp/qr/lookup` first (it tells you if the scan actually landed).
- QR codes never expire; only scheme *bonuses* are time-bound.
- A code can be credited **once**, ever — concurrent duplicate scans are
  rejected server-side.

## 4. Quick test (curl)

```bash
curl -s -X POST https://vastra-loyalty.onrender.com/yourapp/qr/lookup \
  -H "Content-Type: application/json" -H "X-API-Key: <key>" \
  -d '{"code": "<qr token or manual code>"}'

curl -s -X POST https://vastra-loyalty.onrender.com/yourapp/scan \
  -H "Content-Type: application/json" -H "X-API-Key: <key>" \
  -d '{"phone": "9876543210", "code": "<code>", "lat": 26.91, "lng": 75.78}'
```

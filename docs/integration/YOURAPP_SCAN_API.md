# Loyalty Scan API — handoff for the YourApp team

Three server-to-server endpoints for scanning loyalty QR codes from YourApp
(preview a code, redeem it, read a retailer's balance). Call them from the
**YourApp backend only** — the API key must never ship inside the mobile app.

- **Base URL:** `https://vastra-loyalty.onrender.com`
- **Headers (both endpoints):**
  - `Content-Type: application/json`
  - `X-API-Key: <shared secret>` — we share this privately (not in this doc)
- **All bodies and responses are JSON.** Errors look like
  `{ "detail": "<message>", "status": false }`.

---

## 0. `status` — did the call work?

**Every response from these endpoints carries a boolean `status`.**

- `status: true` — the call worked. The API is up and it answered you.
- `status: false` — the call did not work. Something went wrong.

It exists so you can tell *"the API is fine, there is simply no data / the code
was already used"* apart from *"the API failed"* without reading the HTTP code.
The HTTP codes are **unchanged** — a `404` is still a `404`. This is a second,
easier signal, never a replacement.

Two things to keep straight:

- **`status` is only ever the boolean.** A code's own redeemed/available state
  is reported as **`qrStatus`** on `/yourapp/qr/lookup` — that endpoint only.
  (This field used to be called `status`; it was renamed when the boolean took
  the name. If you integrated before Aug 2026, that rename is the only field
  change you need to make.)
- **An already-redeemed code is a *successful* call.** The lookup answers
  `status: true` with `qrStatus: "redeemed"`. `status: false` means we failed
  to answer, not that the answer was "no".

`status: false` also comes back on failures that happen *before* we look at
your request — a wrong `X-API-Key` (`401`), the integration being switched off
(`503`), a rate limit (`429`), a malformed body (`422`) — and on an unhandled
crash on our side, which answers
`500 { "detail": "Internal server error", "status": false }` rather than
dropping the connection. That last case is the one this flag exists for.

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
  "qrStatus": "available",
  "is_box": false,
  "items": 1,
  "product": { "external_id": "VP-9281", "name": "Silk Saree", "sku": "SS-001" },
  "base_points": 50,
  "bonus_points": 25,
  "total_points": 75,
  "scheme": { "id": 2, "name": "Diwali Bonus" },
  "redeemed_at": null,
  "redeemed_by_shop": null,
  "status": true
}
```
- `qrStatus` becomes `"redeemed"` once scanned; then `redeemed_at` and
  `redeemed_by_shop` are filled. `status` stays `true` either way — a
  redeemed code is still a successful lookup (see §0).
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
  "new_balance": 555,
  "status": true
}
```
For a box, `items_registered` = number of items credited and the points
fields are the totals across them. The scan reports its own outcome through
`redeemed`, as it always has — there is no `qrStatus` here.

## 2b. Get a retailer's total points

`POST /yourapp/points`

Returns just the retailer's current points balance — nothing else. Identified
by phone (same matching as the scan endpoint). Read-only.

Request:
```json
{ "phone": "+91 98765 43210" }
```

Response `200`:
```json
{ "total_points": 555, "status": true }
```
- `total_points` is the live wallet balance (points earned from scans minus
  gifts redeemed, etc.) — always current.
- Unlike scan, there's no code here, so the phone is matched across **all**
  manufacturers. If the same phone is registered to two retailers we return
  `409` (data problem — report it) instead of guessing.

Errors: `403 Phone number not registered`, `403 Account is blocked`,
`409 Multiple retailers share this phone number`, `422 Invalid phone number`,
`401 Invalid API key`, `503 YourApp integration is not configured`.

## 3. Errors to handle

Every one of these carries `"status": false` next to `detail`, so
`if (!body.status)` is enough to route into your error path.

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
| 429 | (rate limited) | Back off and retry after a moment (`Retry-After` header is preserved). |
| 500 | `Internal server error` | Something broke on our side. Safe to show "try again"; report it if it persists. |

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

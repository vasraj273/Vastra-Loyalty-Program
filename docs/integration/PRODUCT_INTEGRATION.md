# Product Integration — the catalog, and how QR generation gets a product

> **Status (updated 2026-08-01): the catalog is CSV-imported, not pulled from
> Vastra.** The **reference + snapshot** model in §3–§6 is unchanged and still
> exactly how the system works — what changed is *where the catalog comes
> from*. For v1 the manufacturer imports their own product list as CSV
> (`POST /catalog/products/import`); Vastra's product API is **not** a catalog
> source, because `GET /design/get-design-ids` returns design numbers but no
> design *name*, so it could only ever supply unusable product names.
> `fetch_vastra_products()` remains in `app/vastra_client.py` **dormant and
> uncalled** for a future reconnect. Vastra **OTP login is unaffected and
> always on** (§8.1). QR generation is still entirely **panel-driven**.
> **Legacy, kept only for backward reads:** the `products` table and `GET
> /products` (still read by the Schemes/Claims panel tabs, `/web/generate`,
> and historical `qr_batches.product_id`/`scheme_products.product_id` rows).
>
> Sections below still written in the Vastra-pull tense describe the earlier
> design; §1, §5 and §7–§8 are current.

## 1. The decision

- **The catalog is the manufacturer's own list, imported as CSV.** For v1
  there is a single client who already maintains a product list in another
  system and can export it. Rows live in `product_points` with
  `source = 'import'`.
- **Columns are whatever the manufacturer's file contained.** Only a product
  **name** and a product **code** are required (matched case- and
  format-insensitively); `points` is optional; every other column is preserved
  verbatim in an `attrs` JSON blob and rendered in the panel. The backend does
  not impose a product schema on the client.
- **The product code alone is the identity** → `product_external_id`.
- **Loyalty still references products by `product_external_id`** and stores
  **immutable snapshots** of name/sku on the rows it owns, plus a frozen
  points value. Unchanged from the Vastra-pull design.
- **The per-product points value is loyalty's own data** — set/edited in the
  panel, stored in `product_points`, never taken from anyone else's system.
- **QR generation happens entirely inside the loyalty admin panel**, with no
  catalog lookup at generation time.

Flow:

```
Manufacturer's other system --(export CSV)--> Manufacturer
                                                   |
                                                   v
                        Loyalty Panel -> POST /catalog/products/import
                                                   |
                                                   v
                                          POST /qr/generate (no catalog lookup)
```

## 2. Why this architecture

- **No catalog the client has to re-key.** They already maintain a product
  list elsewhere and can export it; asking them to retype it into a second
  system would guarantee drift. A CSV import is a copy they refresh on their
  own schedule, not a second master.
- **No schema imposed on the client's data.** Only a name and a code are
  required; everything else in their file is preserved verbatim and displayed.
  A backend that demanded fixed columns would break on the next client.
- **Manufacturer controls loyalty economics.** The points-per-scan value is a
  loyalty-program decision, not a catalog fact, so it is the one field set in
  the panel and deliberately kept out of the import unless the CSV supplies it.
- **Snapshots preserve history.** A scan from last year must still show the
  product name/points it had then, even after the product is renamed, deleted,
  or the whole catalog is replaced. This mirrors the ledger's existing
  point-in-time snapshots of `region` and `distributor_id`, and is why delete
  and replace are safe operations.
- **Minimal blast radius.** The QR engine, wallet, scan, schemes, and
  analytics logic stay intact; only the product *source* changed — from a
  local table, to a Vastra pull, to the manufacturer's own import. The
  reference + snapshot model absorbed all three without change.

## 3. Reference + snapshot model

| Where | Stores | When set |
|---|---|---|
| `qr_batches` | `product_external_id`, `product_name`, `product_sku`, `points_per_code` (frozen), `manufacturer_id` | at generation |
| `points_ledger` | `product_external_id`, `product_name`, `product_sku` (+ existing frozen points) | at scan |
| `product_points` | `manufacturer_id`, `product_external_id`, `points`, `name`, `sku`, `attrs` (JSON), `source` | **the catalog itself** — written by `POST /catalog/products/import`; points set/edited in the panel; read by `GET /catalog/products` to pre-fill the generate flow |
| `scheme_products` | `product_id` (**legacy, local products only** — see §8) | at scheme creation |

- **Reference** = the live `product_external_id` (use to group/scope/match).
- **Snapshot** = the copied name/sku/points on `qr_batches`/`points_ledger`
  (use to display history; never re-fetched).
- **No `products` table reads on the QR/scan/claims/analytics/wallet paths.**

## 4. How QR generation works now

```mermaid
sequenceDiagram
  actor M as Manufacturer
  participant P as Loyalty Panel
  participant L as Loyalty API
  M->>P: log in (password, or Vastra mobile + OTP)
  M->>P: import product CSV
  P->>L: POST /catalog/products/import {csv, mode}
  L->>L: parse headers, upsert product_points (source='import')
  L-->>P: {created, updated, skipped, errors, columns}
  P->>L: GET /catalog/products
  L-->>P: {products, columns, source} (no outbound call)
  M->>P: pick product, set/adjust points, quantity
  P->>L: POST /qr/generate { product_external_id, product_name, product_sku, points_per_code, quantity, items_per_box? }
  L->>L: store batch with snapshot + manufacturer_id; mint codes
  L-->>P: 201 { batch_id, codes[], boxes_codes[], actions }
  P->>L: GET /qr/batches/{id}/print (PDF)
```

**No outbound call is involved.** Generation reads nothing but the request
body — not the catalog, not Vastra — so an unknown `product_external_id` is
accepted by design (§5).

**Authentication:** either login works, and the catalog behaves identically
for both. **Password** (`POST /auth/login`), or **Vastra mobile + OTP**
(`POST /auth/vastra/send-otp` → `POST /auth/vastra/verify-otp`, proxied to
Vastra's `loyalty-signup`/`loyalty-verifyotp`). Verify matches the manufacturer
by `external_id` (= Vastra `organization_Id`) or auto-provisions one, and
stores Vastra's `access_token` server-side
(`manufacturers.vastra_access_token`); **nothing reads that token today** — it
is kept for a possible future catalog reconnect, and is wiped on logout.
`current_manufacturer` enforces tenancy on every endpoint below, same as
before.

## 5. Endpoints (implemented)

All manufacturer-scoped. Renamed off the old `/vastra/` prefix — a route
called `/vastra/products` returning hand-imported rows misleads the reader.

**`GET /catalog/products`** — the catalog, plus the free-form column list the
panel renders between the fixed name/code columns and Points:
```json
{
  "products": [{ "external_id": "BNS-01", "name": "Silk Saree",
                 "sku": "BNS-01", "points": 50,
                 "attrs": { "Brand name": "LONDON DREAM", "MRP": "4500" } }],
  "columns": ["Brand name", "MRP"],
  "source": "import"
}
```
Resolves in strict precedence, **never merged**: imported rows (`source:
"import"`) → else the three hardcoded samples when `USE_SAMPLE_PRODUCTS=1`
(`"sample"`; off by default) → else `[]` (`"empty"`) and the panel prompts for
an import. One
import and the samples are gone for that manufacturer. It never calls Vastra.

**`POST /catalog/products/import`** — CSV text as JSON (no multipart), like
the retailer/distributor imports:
```json
{ "csv": "Product name,Product code,Points\nSilk Saree,BNS-01,50\n",
  "mode": "upsert" }
```
→ `{ "created": 1, "updated": 0, "skipped": 0, "errors": [], "columns": [] }`

- **Required columns:** a product name (`name`, `product_name`, `p_name`,
  `item_name`, `design_name`, `product`) and a product code (`code`,
  `product_code`, `p_code`, `sku`, `item_code`, `design_number`, `style_code`,
  `article_code`). Headers normalize via `_norm_header` (lowercase,
  non-alphanumerics collapsed), so `Product Name` / `PRODUCT_NAME` /
  `product name` all match. A file missing either is rejected **whole** (422) —
  a catalog of nameless products can't be printed on a sticker.
- **`points`** optional (`points`, `loyalty_points`, `points_per_scan`).
- **Row-number columns dropped** (`SNo`, `S.No`, `Sr No`, `#`): a render index
  that re-numbers on every export carries no meaning once imported.
- **Null-ish cells blanked**: the literal strings `null`, `N/A`, `-` become
  `""` (source systems export the word "null" for empty cells).
- **`mode: "upsert"`** — match on product code, refresh name/attrs, add new
  rows, delete nothing. Points set in the panel **survive** unless the CSV
  carries a points column. **`mode: "replace"`** — drop this manufacturer's
  imported rows first, leaving legacy `source IS NULL` rows alone.
- Duplicate code within one file: last row wins, reported in `errors`.

**`DELETE /catalog/products/{external_id}`** → `204`, or `404` if it isn't an
imported product of this manufacturer.

**`DELETE /catalog/products`** → `{ "deleted": n }` — clears the whole imported
catalog (the panel's "Delete all", behind a confirmation). Spares legacy rows;
a no-op on an empty catalog, not an error.

**`PUT /catalog/products/{external_id}/points`** — upserts the points value:
```json
PUT /catalog/products/BNS-01/points
{ "points": 50 }
```
On a *sample* product this writes a legacy (`source IS NULL`) override, so
editing a sample's points never flips the account into an imported catalog.

Deleting or replacing **never affects issued QR codes** — `qr_batches` and
`points_ledger` carry their own immutable name/sku snapshots (§3).

**`POST /qr/generate`** — same contract as before, now the panel's only
path (the legacy `{product_id}` body is still accepted, used only by
`/web/generate`):
```json
POST /qr/generate
Authorization: Bearer <loyalty manufacturer token>
{
  "product_external_id": "VP-9281",
  "product_name": "Silk Saree",
  "product_sku": "SS-001",
  "points_per_code": 50,
  "quantity": 100,
  "items_per_box": 10
}
```
- `product_external_id`, `product_name`, `product_sku`, `points_per_code`,
  `quantity` — **required**. `items_per_box` — optional.
- Loyalty validates structure only (bounds, required fields). It does **not**
  validate product existence against Vastra (it has no catalog of its own).
  Unknown `product_external_id` is accepted by design.

## 6. Consequences for other endpoints

- **`/scan`** — writes `product_external_id` + name/sku snapshot to the
  ledger; response `product` carries `external_id` instead of an integer id.
  Unaffected by this change.
- **`/claims`, `/qr/batches*`, `/qr/batches/{id}/print`** — read snapshots
  instead of joining `products`. Unaffected.
- **`/analytics/dashboard`** — `by_product` groups by `product_external_id` +
  snapshot and can only report products **with loyalty activity** (no
  zero-scan rows, since loyalty no longer knows the full catalog). Unaffected.
- **`GET /products`** — kept **read-only**, unmodified, for two remaining
  local readers: the Schemes tab (`scheme_products.product_id` FK — see §8)
  and the Claims tab (historical `product_id` filter). No new rows are
  written to `products` going forward.
- **Legacy product CRUD stays removed:** `POST/PATCH/DELETE /products` and
  `POST /products/import` no longer exist. The catalog's own CRUD lives under
  `/catalog/products` (§5) and writes to `product_points`, never to the legacy
  `products` table.
- **Products panel tab** (`Products.jsx`): Import CSV, inline points editor,
  per-row Delete, Delete all, Export CSV, search by product name or code, and
  client-side pagination (10/25/50/100 rows, default 10). The table pins
  Product name + code left and Points + Actions right, so only the
  manufacturer's own CSV columns scroll horizontally — points stay visible and
  editable next to the product they belong to. Those sticky offsets depend on
  widths set on an inner `.cell` wrapper (a `th`/`td` width is only a hint
  under `table-layout: auto`); changing a frozen column's width means updating
  its neighbour's `left`/`right` offset by the same amount. There is still no
  add-single-product form — CSV import plus delete covers v1.

## 7. Migration status (additive, production-safe; no reseed/drop)

1. ✅ Reference + snapshot model on `qr_batches`/`points_ledger`
   (`product_external_id`, `manufacturer_id`, snapshot columns);
   `_backfill_product_snapshots()` fills pre-migration rows.
2. ✅ `POST /qr/generate` dual contract; `/scan` and all reads repointed off
   the `products` join to `manufacturer_id` + snapshots.
3. ✅ **Pull-based catalog** (superseded by step 6): `app/vastra_client.py` +
   `GET /vastra/products` + `product_points` table + points-override endpoint;
   panel switched to this path.
4. ✅ **Product CRUD/import removed** (`POST/PATCH/DELETE /products`,
   `POST /products/import` deleted). `GET /products` intentionally kept for
   the two legacy readers in §6/§8.
5. ✅ **CSV-imported catalog (2026-08-01):** `product_points` gained `name`,
   `sku`, `attrs`, `source` via `_MIGRATIONS` (additive, applies in place on
   production, no reseed); routes renamed to `/catalog/products*`; the Vastra branch
   removed from the catalog and `fetch_vastra_products()` left dormant;
   `USE_SAMPLE_PRODUCTS` added. Covered by `tests/test_catalog_import.py`.
6. ⏳ **Not done:** migrate `scheme_products` to `product_external_id` (§8);
   update `seed.py` to seed `product_points` instead of `products` rows for
   points, if/when a demo needs it.

The QR engine, wallet, scan, ledger, and points logic are preserved in
substance throughout — only the product *source* and *origination point*
changed.

## 8. Open items

1. ✅ **Resolved (2026-07-16): Vastra's API contract verified live against
   staging.** `app/vastra_client.py` now implements the real endpoints:
   `POST /user/loyalty-signup` / `POST /user/loyalty-verifyotp` (OTP login;
   org profile with `organization_Id`/`organization_name`/`access_token`) and
   `GET /design/get-design-ids` (the org's designs = loyalty "products",
   authenticated with the per-org `access_token`; scoping is per organization,
   so no extra tenant filter is needed). All Vastra responses use a
   `{"status": true|false, "data"|"error": …}` envelope. Config:
   `VASTRA_API_BASE_URL` (staging: the internal `:3000/api/v2` origin — the
   public staging host 301s POSTs away), `VASTRA_API_KEY` (staging value `1`),
   `VASTRA_UDID`/`VASTRA_DEVICE_TYPE` (required device headers, fixed values
   accepted). **The OTP-login half is live and in use; the product half is
   not.** `get-design-ids` returns no `design_name`, which is precisely why the
   catalog moved to CSV import (2026-08-01) — a picker listing design numbers
   is unusable. Reconnecting is a matter of calling the dormant
   `fetch_vastra_products()` again once Vastra exposes names; the per-org
   `access_token` is still stored at login for that day. Access-token expiry
   policy remains unconfirmed with Vastra's dev team, but nothing reads the
   token today, so it can no longer break the Products tab.

   ⚠️ **Deployment gotcha:** `VASTRA_API_BASE_URL` gates OTP login and fails
   closed with `502 "VASTRA_API_BASE_URL is not configured"`. `.env` is
   gitignored and never ships, so a hosted environment (Render) needs it set in
   that platform's own environment settings — otherwise OTP login is dead there
   while working perfectly in local dev. Password login is unaffected.
2. **`scheme_products.product_id` FK gap.** It's a hard FK to the legacy
   local `products.id`. Since manufacturers no longer create local product
   rows, **imported products can't get product-specific scheme bonuses**
   until `scheme_products` migrates to `product_external_id`.
   Existing local products remain scheme-selectable exactly as before; this
   is a known, not-yet-scheduled follow-up.
3. **Manufacturer SSO's (`POST /auth/sso/manufacturer`) continued purpose is
   unclear.** It existed specifically to authenticate the old
   Vastra-backend-originated server-to-server `/qr/generate` call; that call
   pattern no longer exists (generation is panel-driven). Left untouched —
   needs a decision on whether it still serves another purpose in the Vastra
   app, or is now dead code.
4. **`product_points` keys on `product_external_id`** — now the normalized
   **product code** from the manufacturer's CSV. Two consequences: a code
   reused for a different product silently inherits the old row's points on
   re-import, and the same code under two different brands collapses into one
   row (accepted for v1 — the client's codes are unique). If a future CSV
   needs brand-scoped codes, the identity has to change.
5. Optional configurable `points_per_code` ceiling as anti-abuse defense
   (unchanged from before — the manufacturer, not a mobile client, sets this
   value, so the original mobile-client-tampering risk no longer applies,
   but an accidental fat-fingered value is still possible).

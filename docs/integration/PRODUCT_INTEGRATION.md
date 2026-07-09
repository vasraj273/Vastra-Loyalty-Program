# Product Integration — Vastra as the Product System of Record (pull-based)

> **Status: ✅ Implemented.** Vastra is the product catalog; the loyalty
> backend pulls it server-side (`app/vastra_client.py`, `GET
> /vastra/products`) to power the **panel's** product picker. QR generation
> is entirely **panel-driven** — the manufacturer logs into this panel
> directly and generates codes from there; there is no Vastra-app-originated
> server-to-server call for this anymore. Product CRUD/import
> (`POST`/`PATCH`/`DELETE /products`, `POST /products/import`) is **removed**.
> **Legacy, kept only for backward reads:** the `products` table and `GET
> /products` (still read by the Schemes/Claims panel tabs, `/web/generate`,
> and historical `qr_batches.product_id`/`scheme_products.product_id` rows).

## 1. The decision

- **Products are owned exclusively by the Vastra platform.** Vastra is the
  single System of Record (SoR) for the product catalog, product lifecycle,
  product permissions, and product management.
- **The loyalty backend is NOT a product catalog** and never stores products
  as master data. It pulls Vastra's live list on demand, server-side, purely
  to render a picker in the manufacturer panel.
- **Loyalty references products by `product_external_id`** (the Vastra
  product id) and stores **immutable snapshots** of the few product fields it
  needs (name, sku) on the rows it already owns, plus a frozen points value.
- **The manufacturer's per-product points value is loyalty's own data**, not
  Vastra's — the manufacturer sets/edits it directly in the panel. It's
  stored in `product_points` (keyed by `manufacturer_id` +
  `product_external_id`) and merged onto Vastra's live list at read time.
- **QR generation happens entirely inside the loyalty admin panel.** The
  manufacturer never leaves the panel — no Vastra-app screen, no
  server-to-server hop, no second login.

Flow:

```
Manufacturer -> Loyalty Panel -> Loyalty Backend -> Vastra product-list API
                                       |                (server-side, read-only)
                                       v
                                  POST /qr/generate (same backend, no hop out)
```

## 2. Why this architecture

- **One source of truth.** Two catalogs drift. Keeping the product itself
  (name/sku/existence) only in Vastra removes a whole class of "loyalty says
  X, Vastra says Y" bugs.
- **Manufacturer controls loyalty economics.** Unlike the product itself,
  the points-per-scan value is a loyalty-program decision, not a Vastra
  catalog fact — so it's the one field the manufacturer sets locally, in the
  panel, not fetched from Vastra.
- **Credentials and points stay server-side.** The panel (browser) never
  calls Vastra directly and never holds Vastra credentials — `GET
  /vastra/products` is a loyalty-backend proxy (`app/vastra_client.py`).
  This also sidesteps CORS: the panel's CORS allowlist only covers its own
  origins, so a direct browser→Vastra call would additionally require Vastra
  to CORS-allow the panel's domain.
- **Snapshots preserve history.** A scan from last year must still show the
  product name/points it had then, even after Vastra renames or re-prices
  it. This mirrors the loyalty ledger's existing point-in-time snapshots of
  `region` and `distributor_id`.
- **Minimal blast radius.** The QR engine, wallet, scan, schemes, and
  analytics logic stay intact; only the product *source* changed, first from
  a local table to a reference + snapshot, and now from
  Vastra-backend-pushed to loyalty-backend-pulled.

## 3. Reference + snapshot model

| Where | Stores | When set |
|---|---|---|
| `qr_batches` | `product_external_id`, `product_name`, `product_sku`, `points_per_code` (frozen), `manufacturer_id` | at generation |
| `points_ledger` | `product_external_id`, `product_name`, `product_sku` (+ existing frozen points) | at scan |
| `product_points` | `manufacturer_id`, `product_external_id`, `points` | set/edited by the manufacturer in the panel; read by `GET /vastra/products` to pre-fill the generate flow |
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
  participant V as Vastra product-list API
  M->>P: log in (existing panel password login)
  P->>L: GET /vastra/products
  L->>V: GET /products (server-side, VASTRA_API_KEY)
  V-->>L: [{external_id, name, sku}, ...]
  L->>L: merge in product_points overrides for this manufacturer
  L-->>P: [{external_id, name, sku, points}, ...]
  M->>P: pick product, set/adjust points, quantity
  P->>L: POST /qr/generate { product_external_id, product_name, product_sku, points_per_code, quantity, items_per_box? }
  L->>L: store batch with snapshot + manufacturer_id; mint codes
  L-->>P: 201 { batch_id, codes[], boxes_codes[], actions }
  P->>L: GET /qr/batches/{id}/print (PDF)
```

**Why the panel calls Vastra's API through this backend, not directly:**
- **Security:** Vastra's API credential (`VASTRA_API_KEY`) stays server-side,
  never shipped to the browser.
- **CORS:** the panel's CORS allowlist only covers its own origins; proxying
  avoids needing Vastra to CORS-allow the panel domain.

**Authentication:** unchanged — the panel already authenticates the
manufacturer via plain password login (`POST /auth/login`);
`current_manufacturer` enforces tenancy on every endpoint below, same as
before.

## 5. Endpoints (implemented)

**`GET /vastra/products`** (manufacturer-scoped) — proxies Vastra's
product-list API server-side and merges each product's stored points
override:
```json
[{ "external_id": "VP-1", "name": "Silk Saree", "sku": "SS-001", "points": 50 }]
```
Returns `502` if the Vastra call fails or `VASTRA_API_BASE_URL` is unset.

**`PUT /vastra/products/{external_id}/points`** (manufacturer-scoped) —
upserts the manufacturer's points value for a product:
```json
PUT /vastra/products/VP-1/points
{ "points": 50 }
```

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
- **Product CRUD/import removed:** `POST/PATCH/DELETE /products` and
  `POST /products/import` no longer exist. The Products panel tab now shows
  Vastra's live list with an inline points editor only — no add/edit-name/
  delete/import UI.

## 7. Migration status (additive, Neon-safe; no reseed/drop)

1. ✅ Reference + snapshot model on `qr_batches`/`points_ledger`
   (`product_external_id`, `manufacturer_id`, snapshot columns);
   `_backfill_product_snapshots()` fills pre-migration rows.
2. ✅ `POST /qr/generate` dual contract; `/scan` and all reads repointed off
   the `products` join to `manufacturer_id` + snapshots.
3. ✅ **Pull-based catalog:** `app/vastra_client.py` + `GET /vastra/products`
   + `product_points` table + `PUT /vastra/products/{external_id}/points`;
   panel (`Products.jsx`, `GenerateQrModal.jsx`) switched to this path.
4. ✅ **Product CRUD/import removed** (`POST/PATCH/DELETE /products`,
   `POST /products/import` deleted). `GET /products` intentionally kept for
   the two legacy readers in §6/§8.
5. ⏳ **Not done:** migrate `scheme_products` to `product_external_id` (§8);
   update `seed.py` to seed `product_points` instead of `products` rows for
   points, if/when a demo needs it.

The QR engine, wallet, scan, ledger, and points logic are preserved in
substance throughout — only the product *source* and *origination point*
changed.

## 8. Open items

1. **Vastra's real product-list API contract is unknown** (URL, auth
   mechanism, response field names, per-manufacturer scoping). Set via
   `VASTRA_API_BASE_URL`/`VASTRA_API_KEY`; `app/vastra_client.py`'s field
   mapping is a best-effort placeholder until Vastra shares a spec.
2. **`scheme_products.product_id` FK gap.** It's a hard FK to the legacy
   local `products.id`. Since manufacturers no longer create local product
   rows, **new Vastra-sourced products can't get product-specific scheme
   bonuses** until `scheme_products` migrates to `product_external_id`.
   Existing local products remain scheme-selectable exactly as before; this
   is a known, not-yet-scheduled follow-up.
3. **Manufacturer SSO's (`POST /auth/sso/manufacturer`) continued purpose is
   unclear.** It existed specifically to authenticate the old
   Vastra-backend-originated server-to-server `/qr/generate` call; that call
   pattern no longer exists (generation is panel-driven). Left untouched —
   needs a decision on whether it still serves another purpose in the Vastra
   app, or is now dead code.
4. **`product_points` keys on `product_external_id`.** If Vastra's product
   ids are ever unstable/reused, a manufacturer's points override could
   silently detach from the wrong product. Worth confirming stability once
   Vastra's real contract is known.
5. Optional configurable `points_per_code` ceiling as anti-abuse defense
   (unchanged from before — the manufacturer, not a mobile client, sets this
   value, so the original mobile-client-tampering risk no longer applies,
   but an accidental fat-fingered value is still possible).

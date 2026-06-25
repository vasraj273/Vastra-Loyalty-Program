# Product Integration — Vastra as the Product System of Record

> **Status: ✅ Implemented (Phase 1, dual-contract).** The reference + snapshot
> model and the new `POST /qr/generate` contract are live; loyalty no longer joins
> the `products` table on the QR/scan/claims/analytics/wallet paths.
> **Transitional (still present, removed in a later phase):** the legacy
> `{ product_id }` generate body, the Products admin page + product CRUD
> endpoints, and `scheme_products` (still keyed by `product_id`).

## 1. The decision

- **Products are owned exclusively by the Vastra platform.** Vastra is the single
  System of Record (SoR) for the product catalog, product lifecycle, product
  permissions, and product management.
- **The loyalty backend is NOT a product catalog.** It does not create, edit,
  list, or validate products, and it never becomes a second catalog.
- **Loyalty references products by `product_external_id`** (the Vastra product
  id) and stores **immutable snapshots** of the few product fields it needs
  (name, sku, points value) on the rows it already owns.
- **The manufacturer selects the product inside the Vastra App catalog.** The
  mobile app never calls loyalty to fetch products.

Native flow:

```
Manufacturer → Vastra App → Vastra Backend → Loyalty Backend
```
(not `Manufacturer → Vastra App → Loyalty Backend` for product data.)

## 2. Why this architecture

- **One source of truth.** Two catalogs drift. Keeping products only in Vastra
  removes a whole class of "loyalty says X, Vastra says Y" bugs.
- **Trusted economic data.** `points_per_code` has monetary-like value (it's
  frozen onto printed stickers forever). It must come from a **trusted server**
  (Vastra backend), never from an untrusted mobile client.
- **Snapshots preserve history.** A scan from last year must still show the
  product name/points it had then, even after Vastra renames or re-prices it.
  This mirrors the loyalty ledger's existing point-in-time snapshots of `region`
  and `distributor_id`.
- **Minimal blast radius.** The QR engine, wallet, scan, schemes, and analytics
  logic stay intact; only the product *source* changes from a local table to a
  reference + snapshot.

## 3. Reference + snapshot model

| Where | Stores | When set |
|---|---|---|
| `qr_batches` | `product_external_id`, `product_name`, `product_sku`, `points_per_code` (already frozen), **`manufacturer_id`** | at generation |
| `points_ledger` | `product_external_id`, `product_name`, `product_sku` (+ existing frozen points) | at scan |
| `scheme_products` | `product_external_id` (replaces `product_id`) | at scheme creation |

- **Reference** = the live `product_external_id` (use to group/scope/match).
- **Snapshot** = the copied name/sku/points (use to display history; never
  re-fetched).
- **No `products` table reads, no catalog table, no products list endpoint.**

> Structural note for implementers: `qr_batches` currently has **no
> `manufacturer_id`** — batch tenancy is derived through `product_id → products`.
> When products are removed, `qr_batches.manufacturer_id` must be added and
> backfilled **before** that join is dropped, or every batch loses its owner.

## 4. How QR generation works with Vastra as SoR

```mermaid
sequenceDiagram
  actor M as Manufacturer
  participant VA as Vastra App
  participant VB as Vastra Backend (Product SoR)
  participant L as Loyalty API
  M->>VA: choose product (Vastra catalog) + quantity
  VA->>VB: "generate N codes for product P"
  VB->>VB: resolve trusted snapshot: name, sku, points policy
  Note over VB,L: VB authenticates via SSO exchange (manufacturer token)
  VB->>L: POST /qr/generate { product_external_id, product_name, product_sku, points_per_code, quantity, items_per_box? }
  L->>L: store batch with snapshot + manufacturer_id; mint codes
  L-->>VB: 201 { batch_id, codes[], boxes_codes[], actions }
  VB-->>VA: batch result
  VA->>L: GET /qr/batches/{id}/print (PDF)
```

**Origination decision — Vastra Backend → Loyalty (server-to-server).** The
request originates from the Vastra backend, not the mobile app, because:
- **Architecture:** the trusted product snapshot + points policy must be assembled
  where the truth lives (the SoR).
- **Security:** a mobile client is untrusted; if it set `points_per_code`, a
  tampered device or MITM could inflate the value baked into a production print
  run. Server-to-server keeps the points value and `SSO_SECRET` server-side.

**Authentication (recommended):** reuse the existing SSO exchange — the Vastra
backend mints a manufacturer assertion, exchanges it at
`POST /auth/sso/manufacturer` for a loyalty manufacturer token, then calls
`/qr/generate`. `current_manufacturer` still enforces tenancy. No new auth path.

## 5. QR generation contract (implemented)

> Live now. The legacy `{ product_id }` body is still accepted for the
> transitional panel / `/web/generate`; prefer the contract below.

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
  validate product existence (it has no catalog). Unknown `product_external_id`
  is accepted by design.
- Response shape is unchanged from today except integer `product_id` is replaced
  by `product_external_id` (+ snapshot echoed).

## 6. Consequences for other endpoints (implemented)

- **`/scan`** — writes `product_external_id` + name/sku snapshot to the ledger;
  response `product` carries `external_id` instead of an integer id.
- **`/claims`, `/qr/batches*`, `/qr/batches/{id}/print`** — read snapshots instead
  of joining `products`; the product filter on `/claims` becomes
  `product_external_id`.
- **`/schemes`** — accepts `product_external_id`s; loyalty no longer validates
  product existence (a typo simply never matches at scan time). Scheme creation is
  expected to follow the same Vastra App → Vastra Backend → Loyalty path.
- **`/analytics/dashboard`** — `by_product` groups by `product_external_id` +
  snapshot and can only report products **with loyalty activity** (no zero-scan
  rows, since loyalty no longer knows the full catalog). If catalog-complete
  reporting is needed, Vastra produces it on its side.
- **Not yet removed (later phase):** `POST/PATCH/DELETE /products`,
  `POST /products/import`, `GET /products`, and the Products panel tab remain for
  transition. `scheme_products` still references `product_id`, so product-specific
  scheme bonuses currently apply only to legacy `product_id` batches;
  external-only batches still receive all-product schemes.

## 7. Migration plan (additive, Neon-safe; no reseed/drop)

1. ✅ **Additive schema + backfill (no behavior change):** new columns in §3
   (incl. `qr_batches.manufacturer_id`); idempotent startup backfill
   (`_backfill_product_snapshots`) from the still-present `products` join; indexes
   added; `qr_batches.product_id` relaxed to nullable.
2. ✅ **Switch writes/reads:** `/qr/generate` (new contract, legacy fallback) and
   `/scan` write the snapshot; all reads (`/qr/batches*`, `/scan`,
   `/retailer/wallet`, `/claims`, `/analytics/dashboard`) repointed off the
   `products` join to `manufacturer_id` + snapshots.
3. ⏳ **Remove ownership (later phase):** delete product CRUD/import + `GET /products`
   + Products panel tab; migrate `scheme_products` to `product_external_id`; move
   QR/scheme triggering fully to the Vastra-backend path; leave the `products`
   table orphaned (not dropped, to stay Neon-safe).
4. ⏳ **Docs + seed (later phase):** update `seed.py` to emit snapshots.

The QR engine, wallet, scan, ledger, and points logic are preserved in substance
throughout — only the product *source* changes.

## 8. Open items (still to confirm for the later phase)

1. Server-to-server auth: reuse SSO exchange (recommended) vs a dedicated Vastra
   service credential.
2. `by_product` zero-scan rows: **decided — dropped** (loyalty is not the catalog).
3. Optional configurable `points_per_code` ceiling as anti-abuse defense.
4. Confirm scheme creation also flows via the Vastra backend (`scheme_products`
   → `product_external_id`).

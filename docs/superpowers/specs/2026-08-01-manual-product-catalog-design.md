# Manual product catalog (CSV import) — design

**Date:** 2026-08-01
**Status:** approved, ready for implementation planning

## Problem

The product catalog is currently pulled from Vastra's `get-design-ids` API using the
`vastra_access_token` stored at OTP login. That path is not ready for v1:

- `get-design-ids` returns `design_id` / `design_number` but **no design name**, so
  `fetch_vastra_products` falls back to printing the design number as the product name.
- Only one client is going live. They already maintain a product list elsewhere and can
  export it as CSV.

For v1 the manufacturer imports their catalog as CSV. The Vastra API path stays in the
codebase, switched off, to be enabled later without a code change.

## Decisions

| Question | Decision |
|---|---|
| Catalog source | Imported CSV is primary. Vastra API and hardcoded samples are fallbacks behind env flags. |
| Sources merged? | **No — strict precedence.** Never merged. |
| Storage | Extend the existing `product_points` table (additive migrations). |
| Free-form columns | Whatever the CSV had, in CSV order, stored as JSON in `attrs`. |
| Required columns | A product-name column and a product-code column. Everything else optional. |
| Identity | Normalized product code alone → `product_external_id`. |
| Points column | Optional in the CSV; otherwise 0 and set in the panel. |
| Re-import | Manufacturer chooses **Update** or **Replace** at import time. |
| Panel actions | Import CSV, edit points inline, delete row. No add-single-product form. |
| Routes | Renamed off the `/vastra/` prefix to `/catalog/products`. |

## Flags

Module-level env config in `app/main.py`, same convention as `QR_BASE_URL` and
`SSO_SECRET`:

```python
USE_VASTRA_API      = os.environ.get("USE_VASTRA_API", "0") == "1"       # default OFF
USE_SAMPLE_PRODUCTS = os.environ.get("USE_SAMPLE_PRODUCTS", "1") == "1"  # default ON for now
```

`USE_SAMPLE_PRODUCTS` defaults **on** today so the QR → scan → redeem flow stays testable.
At go-live it is set to `0` and the empty state appears. Both flags are documented in
`.env.example` and `DEPLOY.md`.

### Catalog resolution — `GET /catalog/products`

Strict precedence, evaluated per manufacturer:

1. The manufacturer has imported products → **return those**.
2. Else `USE_VASTRA_API` → Vastra `get-design-ids` via `fetch_vastra_products`, merged with
   `product_points` overrides exactly as today. No stored `vastra_access_token` → `409`
   (the current behaviour, restored).
3. Else `USE_SAMPLE_PRODUCTS` → the three hardcoded `_SAMPLE_PRODUCTS`.
4. Else `[]` → the panel renders the empty state.

Consequence, accepted: once a manufacturer imports even one product, samples and the
Vastra list are invisible to them.

## Storage

Additive columns on `product_points` via `_MIGRATIONS` (`ADD COLUMN IF NOT EXISTS` on PG,
PRAGMA-checked on SQLite). No reseed, no destructive change — safe on Neon.

```python
("product_points", "name",   "TEXT"),
("product_points", "sku",    "TEXT"),
("product_points", "attrs",  "TEXT"),   # JSON object, insertion-ordered
("product_points", "source", "TEXT"),   # 'import' for imported rows, NULL for legacy
```

The same columns are added to the `SCHEMA` `CREATE TABLE` so fresh databases match.

`source` is load-bearing. A pre-existing `product_points` row means "points override for a
Vastra design" and has no name. Without the marker those rows would surface as nameless
imported products and would suppress the Vastra/sample fallbacks. Only
`source = 'import'` rows count as an imported catalog.

`product_points` has a composite primary key and no serial `id`, so `_ID_TABLES` needs no
change.

### `attrs` JSON

Every CSV column that is not name / code / points, keyed by the **original header text**
(e.g. `"Sub Category"`, not `sub_category`) so the panel can display it verbatim. Python
dicts and `json.dumps` preserve insertion order, so CSV column order round-trips without a
separate ordering table.

The catalog response carries a `columns` list — the union of `attrs` keys across the
manufacturer's rows, in first-seen order — so the panel does not have to infer the column
set itself.

## CSV parsing

Header normalization: lowercase, strip, collapse runs of non-alphanumerics to `_`. So
`Product Name`, `PRODUCT_NAME`, `product name` and `Product  Name` all match.

| Field | Accepted headers (post-normalization) |
|---|---|
| name (**required**) | `name`, `product_name`, `item_name`, `design_name`, `product` |
| code (**required**) | `code`, `product_code`, `sku`, `item_code`, `design_number`, `style_code`, `article_code` |
| points (optional) | `points`, `loyalty_points`, `points_per_scan` |
| ignored | `sno`, `s_no`, `serial`, `sr_no`, `no`, `#` |
| everything else | free-form → `attrs` |

Rules:

- **Missing a required column** → the whole import fails with a message naming the accepted
  spellings. Nothing is written.
- **Serial-number columns are dropped.** They are a render index that re-numbers on every
  export and carry no meaning after import.
- **Null-ish values normalize to empty**: the literal strings `null`, `NULL`, `N/A`, `-`
  become `""`. The source system exports the literal text `null` for empty cells; without
  this the panel would display "null" across the table.
- **Blank name or blank code** → row skipped, counted in `skipped`, reported with its line
  number.
- **Duplicate code within one file** → last row wins, reported as a warning in `errors`.
- **Non-numeric points** → row skipped with an error naming the line.

CSV text arrives as JSON (no `python-multipart`), matching `/retailers/import` and
`/distributors/import`.

## Endpoints

All manufacturer-scoped via `current_manufacturer`, all filtered by
`manufacturer_id`.

```
GET    /catalog/products                       -> {products: [...], columns: [...], source: "import"|"vastra"|"sample"|"empty"}
POST   /catalog/products/import                {csv, mode: "upsert"|"replace"}
DELETE /catalog/products/{external_id}
PUT    /catalog/products/{external_id}/points  {points}
```

`GET /vastra/products` and `PUT /vastra/products/{external_id}/points` are renamed. A route
named `/vastra/products` that returns hand-imported rows misleads the next reader. Two call
sites in `panel/src/api.js` change.

Import response: `{created, updated, skipped, errors, columns}`. The first four match the
shape `panel/src/components/ImportResult.jsx` already renders for Customers and
Distributors, so the result UI is reused unchanged.

**`mode: "upsert"`** — match on normalized product code within the manufacturer. Existing
rows get name and `attrs` refreshed; new rows are inserted. Points are **preserved** unless
the CSV carries a points column. Nothing is deleted. New columns appearing in the second
file are appended to the table.

**`mode: "replace"`** — delete this manufacturer's `source = 'import'` rows, then insert,
in a single transaction. `product_points` rows with `source IS NULL` (legacy Vastra
overrides) are left alone.

`DELETE` removes one imported row. Deleting or replacing **never affects issued QR codes** —
`qr_batches` and `points_ledger` carry immutable `product_name` / `product_sku` snapshots,
which is exactly what that snapshot design is for.

## Untouched by this feature

`POST /qr/generate` still receives `product_external_id` + `product_name` + `product_sku` +
`points_per_code` from the panel and does no catalog lookup. The QR, scan, claims, wallet
and analytics paths are unchanged. This feature only changes where the panel's product
*list* comes from.

## Panel

### Products tab (`panel/src/tabs/Products.jsx`)

- Columns are driven by the API's `columns` list: **the CSV's own columns, in CSV order,
  then Points, then Actions.**
- Header reads **"Points"**, not "Points / scan".
- Wide catalogs (the real client list has 11+ columns) scroll horizontally **inside the
  table card**; the page body never scrolls sideways. Points and Actions stay reachable
  without scrolling to the far right.
- Empty state: *"No products yet — add them using the Import CSV button."*
- Row actions: **Edit points** (existing inline editor) and **Delete** (via `useConfirm`).
- The hint text about syncing from Vastra is replaced.
- **Export CSV** exports the dynamic column set (CSV columns + Points), not the fixed
  name / sku / points triple it exports today.

`GET /catalog/products` returns an **object**, where `/vastra/products` returned a bare
array. Both consumers change: `Products.jsx` reads `.products` / `.columns`, and
`panel/src/components/GenerateQrModal.jsx` reads `.products`. `GenerateQrModal` otherwise
keeps working — it only needs `external_id`, `name`, `sku` and `points`, which every source
provides.

### Import flow

New **Import CSV** button next to Generate QR / Export CSV.

1. Pick file.
2. If the manufacturer's catalog is **empty** → import directly as `upsert`.
3. If the catalog is **non-empty** → the modal presents two choices:
   - **Update existing list** → `mode: "upsert"`.
   - **Replace entire list** → `mode: "replace"`, behind a second confirmation naming the
     number of products about to be removed.
4. Result rendered by the existing `ImportResult.jsx`.

The three-way choice lives inside the import modal rather than as a chained prompt, because
`useConfirm` (`panel/src/confirm.jsx`) resolves to a boolean and cannot express it.

## Testing

New `tests/test_catalog_import.py`, following the existing pytest fixtures in
`tests/conftest.py`:

- Header alias and case tolerance — `Product Name` / `PRODUCT_NAME` / `product name` all map
  to name; `Product code` maps to code.
- Missing a required column rejects the import and writes nothing.
- Serial-number columns are dropped; `null` / `N/A` / `-` normalize to empty.
- Free-form columns round-trip through `attrs` in CSV order, with original header text.
- Upsert refreshes name/attrs, adds new rows, and preserves panel-set points when the CSV
  has no points column.
- Upsert overwrites points when the CSV **does** carry a points column.
- Replace clears prior imported rows but leaves legacy `source IS NULL` rows intact.
- Duplicate code within one file — last row wins, warning reported.
- Tenant isolation — one manufacturer's import is invisible to another.
- Precedence chain — imported beats samples; samples appear only when the catalog is empty;
  `USE_VASTRA_API=1` with no stored token returns 409; all flags off with empty catalog
  returns `[]`.
- Delete removes the row and leaves already-issued QR batches readable.

## Documentation

`CLAUDE.md` is updated: the products section rewritten around the flags and the manual
catalog, the route rename recorded, and the stale "There is no test suite" line corrected
(`tests/` has existed for some time). `DEPLOY.md` and `.env.example` gain the two flags.

## Deferred

- Merging an imported catalog with the Vastra list. v1 is strict precedence.
- `scheme_products` still keys off the legacy local `products.id`, so product-specific
  scheme bonuses do not cover imported products. Unchanged by this work, still open.
- An add-single-product form. CSV import plus delete covers v1.

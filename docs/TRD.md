# Technical Requirements Document — Vastra Loyalty Program

**Status:** Live (Render + Neon) · **Last updated:** 2026-06-24

Companion to **PRD.md** (product) and **CLAUDE.md** (contributor conventions).
This document describes the technical design as built.

## 1. Architecture

Single FastAPI service (`app/main.py`) serving three surfaces from one container:

```
                 ┌──────────────────────── FastAPI (app/) ────────────────────────┐
  Vastra app ───▶│  REST API  ──┐                                                  │
  YourApp    ───▶│  /web/*  (plain-HTML webviews: home, scan, shop, claims,        │
  Panel SPA  ───▶│            generate)                                            │
                 │  /panel  (React build from panel/dist)                          │
                 │            └──▶ app/database.py  ──▶  SQLite (dev) / Postgres(prod)│
                 └─────────────────────────────────────────────────────────────────┘
```

- **Backend:** Python 3.12+, FastAPI, Pydantic v2, Uvicorn.
- **PDF/QR:** `qrcode[pil]`, `reportlab` (A4 label sheets).
- **DB driver:** `psycopg[binary]` (Postgres); stdlib `sqlite3` otherwise.
- **Panel:** React + Vite (`panel/`), built to `panel/dist`, served at `/panel`.
  `panel/src/api.js` is the only fetch layer. Navigation is a top-right burger
  menu (`App.jsx`); the India map clusters via `leaflet.markercluster`; a
  promise-based `useConfirm()` (`confirm.jsx`) gates every points-changing action
  (adjust/transfer/approve/reject) with a themed confirmation dialog. Every data
  tab exports to CSV via a shared client-side helper (`utils/csv.js` — RFC-4180 +
  BOM `Blob` download, no dependency). QR generation runs in a modal
  (`components/GenerateQrModal.jsx`) calling the existing `/qr/*` endpoints, so the
  standalone `/web/generate` page is no longer linked from the panel.
- **Webviews:** static HTML/JS in `app/web/` served via `FileResponse`. Retailer
  pages (`home/scan/shop/claims`) carry a shared burger menu; `scan.html` plays a
  count-up + confetti animation on a successful scan and auto-restarts the camera
  on "Scan another".
- **Theme:** Vastra brand palette — blue `#0191D0`, dark blue `#1D466F`, coral
  `#FB624B`, text `#112134`, light base; status colors kept (green/amber). Defined
  as CSS variables in `panel/src/styles.css` `:root` and mirrored in each
  `app/web/*.html` inline `:root`. Font is a Helvetica system stack (no web font);
  QR codes remain black/white for scan reliability.

## 2. Data model

Tables (`app/database.py` `SCHEMA`, evolved additively via `_MIGRATIONS`):

| Table | Purpose | Key columns |
|---|---|---|
| `manufacturers` | Manufacturer + super-admin accounts | `username`, `password_hash`, `display_name`, `is_admin` |
| `auth_tokens` | Manufacturer/admin bearer tokens | `token`, `manufacturer_id` |
| `products` | Catalog | `manufacturer_id`, `name`, `sku`, `loyalty_points` |
| `retailers` | Shops | `manufacturer_id`, `shop_name`, `region`, `username`, `password_hash`, `lat`, `lng`, `location_source`, `address`, `distributor_id` |
| `retailer_tokens` | Retailer bearer tokens | `token`, `retailer_id` |
| `distributors` | Distributor layer (tracking only, no login/points) | `manufacturer_id`, `name`, `phone`, `region` |
| `schemes` / `scheme_products` | Time-bound bonus campaigns + scope | `bonus_points`, `start_date`, `end_date` |
| `qr_batches` | Generation batch | `product_id`, `quantity`, `points_per_code` (frozen) |
| `qr_codes` | Individual codes | `token`, `manual_code`, `batch_id`, `is_parent`, `parent_token`, `redeemed_at`, `redeemed_by` |
| `points_ledger` | Typed transaction log | `entry_type`, `points`, `base_points`, `bonus_points`, `scheme_id`, `region`, `lat`, `lng`, `distributor_id`, `scanned_at` |
| `gifts` / `gift_claims` | Rewards catalog + claims | `points_cost`, `reference`, status |

Every tenant-owned row carries `manufacturer_id`.

## 3. Database backend (dual)

`app/database.py` is **dual-backend**: Postgres when `DATABASE_URL` is set, SQLite
otherwise. Application code is written in **SQLite style everywhere** (`?`
placeholders, `cur.lastrowid`, `datetime('now')`, `:name` params); a `_PGConn`
adapter translates to psycopg at runtime.

- Tables using `cur.lastrowid` on INSERT must be in `_ID_TABLES` (adapter appends
  `RETURNING id` on PG).
- Avoid `%` literals and inline `:word` time formats (would break translation).
- **Schema evolution is additive & idempotent.** New tables → `SCHEMA`
  (`CREATE TABLE IF NOT EXISTS`); new columns → `_MIGRATIONS` (`ADD COLUMN IF NOT
  EXISTS` on PG, PRAGMA-checked on SQLite). `migrate()` runs every startup.
- Startup does `init_db()` + `migrate()` + `_backfill_coords()` — **never seeds**.
  `seed.py`/`reset_db()` are destructive (local/initial only) and do **not** run
  `_MIGRATIONS`.
- **No `;` in `SCHEMA` comments.** The PG `executescript` splits on `;`; a
  semicolon in a `--` comment would split a statement (SQLite tolerates it, so it
  only fails on Postgres at deploy). `executescript` now strips full-line `--`
  comments before splitting, but keep schema comments semicolon-free.

## 4. Authentication & authorization

- Two principals, opaque bearer tokens (`app/auth.py`). Sent as
  `Authorization: Bearer <t>` or `?token=` (for print-PDF links).
- Dependencies: `current_manufacturer`, `current_admin`, `current_retailer`.
- Passwords: PBKDF2 (`hash_password`/`verify_password`).
- **Multi-tenancy:** manufacturer endpoints filter by `current_manufacturer["id"]`;
  retailer endpoints derive the retailer from the token, never the body — points
  can only be credited to the logged-in retailer. Cross-manufacturer scans → 403.
- **Retailer login auto-creation:** on `POST /retailers`, username = first
  alphanumeric word of the shop name (lowercased), password = `<username>123`,
  id appended on clash (`username` is UNIQUE).

## 5. API surface

Authoritative list at `/docs`. Principal endpoints:

- **Auth:** `POST /auth/login`, `/auth/logout`, `/auth/retailer/login`,
  `/auth/retailer/logout`, `GET /auth/me`, `/retailer/me`.
- **Admin:** `GET|POST /admin/manufacturers`.
- **Catalog:** `GET|POST /products`, `PATCH|DELETE /products/{id}`,
  `POST /products/import`; `GET|POST /schemes`, `DELETE /schemes/{id}`;
  `GET|POST /gifts`, `PATCH|DELETE /gifts/{id}`.
- **Bulk import (CSV-as-JSON):** `POST /retailers/import`,
  `POST /distributors/import`, `POST /products/import`.
- **Retailers:** `GET|POST /retailers`, `PATCH|DELETE /retailers/{id}`,
  `POST /retailers/{id}/adjust`, `POST /retailers/transfer`,
  `POST /retailers/import` (CSV-as-JSON bulk create), `POST /retailer/location`.
- **Distributors:** `GET|POST /distributors`, `PATCH|DELETE /distributors/{id}`.
- **QR:** `POST /qr/generate`, `GET /qr/batches`, `GET /qr/batches/{id}`,
  `POST /qr/batches/{id}/save`, `GET /qr/batches/{id}/print`,
  `DELETE /qr/batches/{id}`, `GET /qr/codes/{token}/image`.
- **Scan & rewards:** `POST /scan`, `GET /retailer/wallet`, `/retailer/shop`,
  `POST /retailer/claim`, `GET /retailer/claims`; `GET /claims`,
  `GET /gift-claims`, `POST /gift-claims/{id}/approve|reject`.
- **Analytics:** `GET /analytics/dashboard`.
- **Public/webview:** `GET /public/cities`, `/web`, `/web/scan[/{token}]`,
  `/web/shop`, `/web/claims`, `/web/generate`.

## 6. Core algorithms

### 6.1 Points on scan (`POST /scan`)
1. Resolve code by `token` or `manual_code`; reject unknown (404), already-redeemed
   (409), cross-manufacturer (403).
2. Determine codes to register (a parent box → all unredeemed children).
3. Base = `qr_batches.points_per_code` (frozen). Bonus = most generous active scheme
   covering the product (date-bound, no stacking).
4. Mark codes redeemed; write one `points_ledger` (`entry_type='scan'`) row per code
   with base/bonus split, scheme, region, the scan's `lat/lng`, and the retailer's
   current `distributor_id` (point-in-time attribution).
- **Balance = `SUM(points)`**; scan analytics filter `entry_type='scan'`.

### 6.1b Distributors
- `distributors` (manufacturer-scoped) is tracking-only: no login, wallet, or
  points. `retailers.distributor_id` links a retailer to one.
- `POST /retailers/import` parses CSV text (stdlib `csv`); a `distributor` column
  is resolved via `_find_or_create_distributor(db, mid, name)` (case-insensitive,
  per manufacturer); retailers get auto-logins (`_assign_retailer_login`); rows
  with a duplicate `shop_name` are skipped. Returns generated credentials.
- Dashboard `by_distributor` sums each distributor's connected **retailers'**
  scans/points — never points held by the distributor.

### 6.1d Dashboard analytics (`GET /analytics/dashboard`)
- `totals` includes `retailers`, `products`, `scans`, `points_awarded`,
  `codes_issued`, and redemption-request counts from `gift_claims`:
  `redeem_total`, `redeem_pending`, `redeem_approved`.
- `by_region` rolls scans/points up by region; blank/NULL region groups under
  `'Unspecified'` via `COALESCE(NULLIF(region, ''), 'Unspecified')`.
- `by_month` is a `{month:'YYYY-MM', generated, scanned}` series (merged in Python
  from two queries — generation `COUNT` over `qr_codes.created_at` joined to the
  manufacturer's products, scans `COUNT` over `points_ledger.scanned_at` where
  `entry_type='scan'`). Month buckets use `substr(x, 1, 7)` (portable across
  SQLite/Postgres — **not** `strftime`).
- The panel renders `by_month` as two themed SVG bar charts
  (`panel/src/components/BarChart.jsx`, a viewBox chart that scales to the card —
  no charting dependency) under a **year selector**: month-wise generation, and
  generated-vs-scanned grouped bars. Stat cards are all-time; charts are per-month
  within the selected year and show a per-year subtotal so bars reconcile to cards.

### 6.1e Claims listing & box grouping (`GET /claims`)
- A box (parent) scan writes one `points_ledger` row per child code (all sharing
  the same `scanned_at`, retailer, product). To avoid flooding the Claims list,
  `list_claims` joins `qr_codes q ON q.token = l.token` and groups by
  `COALESCE(q.parent_token, l.token)` — children of one box (same `parent_token`)
  collapse to a single row; plain scans (NULL `parent_token`) group on their unique
  `token`, i.e. one row each. The row returns `item_count` (`COUNT(*)`), summed
  `points`/`base_points`/`bonus_points`, `parent_token` (`MAX`), and `id`
  (`MIN(l.id)`). `total` counts grouped rows via a `GROUP BY` subquery.
- Done entirely at query time — **no schema change**, and it tidies box scans
  already stored on Neon. The non-aggregated SELECT columns are repeated in
  `GROUP BY` (identical within a group) to satisfy Postgres strict grouping; stays
  `?`-placeholder / sqlite-style for the dual backend.
- The panel walks every page (`limit`/`offset`) to build the Claims CSV export.

### 6.1c CSV imports
- All three imports (`/retailers/import`, `/distributors/import`,
  `/products/import`) take CSV text as JSON (stdlib `csv`, no `python-multipart`)
  and return `created`/`skipped`/`errors`.
- `/products/import` reads the points value under several header aliases
  (`_row_points`: `PointsPerScan`, `points`, `points_per_scan`, `loyalty_points`,
  …) and **upserts by SKU** — a product you already own is *updated* (name +
  points) instead of skipped; a SKU owned by another account is skipped. Also
  returns `updated`.

### 6.2 Location
- **Shop pin + address, latest-wins:** `POST /retailer/location` (called once per
  scanning session by `scan.html`) updates `retailers.lat/lng`, sets
  `location_source='gps'`, re-derives `region` via `geo.nearest_city`, and sets
  `retailers.address` via `geo.reverse_address` (free OpenStreetMap Nominatim,
  best-effort, ~5s timeout; `COALESCE`s to keep the previous value on failure).
  No lock — each session refreshes it, so a wrong registered city self-corrects.
- **Client capture (`app/web/scan.html`):** location is requested **up front**
  before scanning via a trust-framed popup; high-accuracy GPS
  (`enableHighAccuracy:true`, 20s timeout, 30s cache), once per session
  (`sessionStorage`), sent as optional `lat/lng` on `/scan`. Secure context
  required. If denied/blocked the popup is dismissed (✕) and the scan proceeds on
  the registered city — never hard-blocked.
- **Panel:** the Customers "Location" column shows `address` + a Google Maps
  `?q=lat,lng` "View on map" link; the city falls back to `region`.
- **Map (`/analytics/dashboard` → `map_points`):** scan events grouped by retailer +
  rounded coords (~11m), weighted by count, clustered client-side
  (`leaflet.markercluster`, zoom 18), falling back to the shop pin.

### 6.3 QR payload
- Each code encodes `{QR_BASE_URL}/{token}` (default `/web/scan`). The token is a
  `uuid4().hex` — opaque, unguessable, validated server-side. `scan.html`
  cosmetically rewrites the address bar to `/web/scan` after reading the token; an
  unauthenticated open redirects to `/web?next=…` and `home.html` likewise strips
  the token from the address bar (kept in memory) before showing the login form.

### 6.4 Printable PDF (`app/pdf_service.py`)
- `build_pdf` lays child stickers on a 4×6 grid; box (parent) stickers go on their
  own page in a 2×3 grid with a border. Each box sticker stacks **title →
  QR → product name → manual code, all inside the border** — the box QR is sized
  `min(cell) − 38mm` to leave room for both label lines (a larger QR previously
  pushed the labels onto/below the bottom border).

## 7. Configuration

| Env var | Purpose |
|---|---|
| `DATABASE_URL` | Postgres/Neon **pooled** connection string. Unset → local SQLite `qr_api.db`. |
| `QR_BASE_URL` | URL prefix baked into every QR (set to deployed HTTPS origin + `/web/scan` before any production print run). |

## 8. Deployment

- **Dockerfile** builds the panel, then runs the API serving `/`, `/panel`,
  `/web/*`. Render (Docker web service) + Neon Postgres.
- **Auto-deploy** from GitHub `main`; container creates/migrates tables on boot,
  never seeds — data persists across deploys.
- Free tier spins down on idle (~50s cold start). See **DEPLOY.md**.

## 9. Security notes
- Parameterized queries throughout (no string-built SQL) → no SQL injection via
  tokens/inputs.
- Passwords hashed (PBKDF2); tokens opaque and revocable.
- Known backlog (not yet implemented): rate limiting, scan/redeem
  race-condition (TOCTOU) hardening, broader input/XSS review. Treat production
  Neon data as real — never reseed/drop it.

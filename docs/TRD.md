# Technical Requirements Document — Vastra Loyalty Program

**Status:** Live (Render + Neon) · **Last updated:** 2026-06-18

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
  `panel/src/api.js` is the only fetch layer.
- **Webviews:** static HTML/JS in `app/web/` served via `FileResponse`.

## 2. Data model

Tables (`app/database.py` `SCHEMA`, evolved additively via `_MIGRATIONS`):

| Table | Purpose | Key columns |
|---|---|---|
| `manufacturers` | Manufacturer + super-admin accounts | `username`, `password_hash`, `display_name`, `is_admin` |
| `auth_tokens` | Manufacturer/admin bearer tokens | `token`, `manufacturer_id` |
| `products` | Catalog | `manufacturer_id`, `name`, `sku`, `loyalty_points` |
| `retailers` | Shops | `manufacturer_id`, `shop_name`, `region`, `username`, `password_hash`, `lat`, `lng`, `location_source` |
| `retailer_tokens` | Retailer bearer tokens | `token`, `retailer_id` |
| `schemes` / `scheme_products` | Time-bound bonus campaigns + scope | `bonus_points`, `start_date`, `end_date` |
| `qr_batches` | Generation batch | `product_id`, `quantity`, `points_per_code` (frozen) |
| `qr_codes` | Individual codes | `token`, `manual_code`, `batch_id`, `is_parent`, `parent_token`, `redeemed_at`, `redeemed_by` |
| `points_ledger` | Typed transaction log | `entry_type`, `points`, `base_points`, `bonus_points`, `scheme_id`, `region`, `lat`, `lng`, `scanned_at` |
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
- **Catalog:** `GET|POST /products`, `PATCH|DELETE /products/{id}`;
  `GET|POST /schemes`, `DELETE /schemes/{id}`; `GET|POST /gifts`,
  `PATCH|DELETE /gifts/{id}`.
- **Retailers:** `GET|POST /retailers`, `PATCH|DELETE /retailers/{id}`,
  `POST /retailers/{id}/adjust`, `POST /retailers/transfer`,
  `POST /retailer/location`.
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
   with base/bonus split, scheme, region, and the scan's `lat/lng`.
- **Balance = `SUM(points)`**; scan analytics filter `entry_type='scan'`.

### 6.2 Location
- **Shop pin:** `retailers.lat/lng` + `location_source` (`city` from
  `geo.coords_for(region)`, or `gps` locked on first `POST /retailer/location`).
- **Optional region backfill:** if `region` is blank, the first GPS fix
  reverse-geocodes via `geo.nearest_city(lat,lng)` (offline haversine over
  `CITY_COORDS`) and sets `region`.
- **Per-scan capture (client, `app/web/scan.html`):** captured once per session
  (`sessionStorage`), low-accuracy (`enableHighAccuracy:false`, 20s timeout, cached
  fix), reused for every scan that session; sent as optional `lat/lng` on `/scan`.
  Requires a secure context; result screen shows status + a tap-to-share fallback.
- **Map (`/analytics/dashboard` → `map_points`):** scan events grouped by retailer +
  rounded coords (~110m), weighted by count, falling back to the shop pin.

### 6.3 QR payload
- Each code encodes `{QR_BASE_URL}/{token}` (default `/web/scan`). The token is a
  `uuid4().hex` — opaque, unguessable, validated server-side. `scan.html`
  cosmetically rewrites the address bar to `/web/scan` after reading the token.

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-tenant loyalty-program backend for the VastraApp ecosystem. Manufacturers generate QR codes (printed on product/box stickers) in the **Vastra** app; retailers scan them in **YourApp** to earn points and redeem gifts. One FastAPI service serves three surfaces:

- **REST API** (`app/`) — the source of truth for Vastra, YourApp, and the panel.
- **React admin panel** (`panel/`, built to `panel/dist`, served at `/panel`) — manufacturer + super-admin UI.
- **Plain-HTML webview pages** (`app/web/`, served at `/web/*`) — the temporary mobile UI loaded inside the Vastra/YourApp webviews (`/web` retailer home, `/web/scan`, `/web/shop`, `/web/claims`, `/web/generate`).

## Commands

```powershell
# Backend (Python 3.12+)
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --port 8000        # API + webviews + built panel
# API docs at /docs, OpenAPI at /openapi.json

# Seed / reset DATA (wipes! never run against a DB with real data)
.\.venv\Scripts\python seed.py

# Panel (Node)
npm install --prefix panel
npm run dev --prefix panel        # http://localhost:5173, proxies /api -> :8000
npm run build --prefix panel      # required before the API can serve /panel

# Bulk retailer onboarding (offline tools, not website features)
.\.venv\Scripts\python import_retailers.py sample_retailers.csv
.\.venv\Scripts\python backfill_retailer_logins.py   # give login-less retailers a login
```

There is no test suite. Verify changes by running the server and exercising endpoints (Swagger at `/docs`, or `Invoke-RestMethod`). Demo logins after seeding: `admin/admin123` (super admin), `surya/surya123` & `heritage/heritage123` (manufacturers), retailer logins are `<shop-first-word>/<that>123` (e.g. `kumar/kumar123`).

## Database — the central design

`app/database.py` is **dual-backend**: PostgreSQL when `DATABASE_URL` is set (production / Neon), SQLite otherwise (local dev, no setup). Application code is written in **sqlite style everywhere** (`?` placeholders, `cur.lastrowid`, `db.executescript`, named `:param` dicts, `datetime('now')`/`date('now')`); a thin `_PGConn` adapter translates these to psycopg at runtime. Consequences when editing SQL:

- New code keeps using `?`, `cur.lastrowid`, `datetime('now')` — do not write Postgres-specific SQL in `app/main.py`.
- **Any table whose INSERT uses `cur.lastrowid` must be listed in `_ID_TABLES`** in `database.py`, or `lastrowid` is `None` on Postgres (the adapter appends `RETURNING id` only for those tables).
- Avoid `%` literals (e.g. `LIKE '%x%'`) and inline `:word` time formats — the adapter's `?`→`%s` and `:name`→`%(name)s` translation would break.
- **No `;` inside `SCHEMA` comments.** The PG adapter's `executescript` splits on `;`; a semicolon in a `--` comment would cut a statement in two (SQLite tolerates it, so it only breaks on Postgres at deploy). The adapter now strips full-line `--` comments before splitting, but keep comments semicolon-free.

**Never reseed or drop the production (Neon) database to apply schema changes.** Schema evolution is additive and idempotent: add new tables to `SCHEMA` (created via `CREATE TABLE IF NOT EXISTS`), and add new columns to the `_MIGRATIONS` list. `migrate()` runs on every startup and applies missing columns in place (`ADD COLUMN IF NOT EXISTS` on PG; PRAGMA-checked on SQLite). The app startup only does `init_db()` + `migrate()` + `_backfill_coords()`; it never seeds. `seed.py`/`reset_db()` are destructive and for local dev or one-time initial seeding only.

## Architecture essentials

**Two auth principals, token-based** (`app/auth.py`). Manufacturers/super-admin authenticate via `auth_tokens`; retailers via `retailer_tokens`. Dependencies: `current_manufacturer`, `current_admin` (super admin only, owns no catalog data), `current_retailer`. Tokens are opaque; sent as `Authorization: Bearer` or `?token=` (the latter lets the print-PDF link open in a tab). Passwords are PBKDF2 (`hash_password`/`verify_password`).

**Retailer logins are auto-created.** `POST /retailers` (and `seed.py`/`backfill_retailer_logins.py`) derive a login from the shop name: username = first word, lowercased alphanumerics; password = `<username>123`; a clash gets the retailer id appended (the `username` column is `UNIQUE`). The creation response returns the plaintext password once so the panel can show the manufacturer the new credentials.

**Multi-tenancy.** Every product/retailer/distributor/scheme/batch/gift/claim/ledger row carries `manufacturer_id`; all manufacturer endpoints filter by `current_manufacturer["id"]`. A retailer belongs to one manufacturer; cross-manufacturer scans are rejected. Retailer-facing endpoints (`/scan`, `/retailer/*`) derive the retailer from the token — never from a request body — so points can only be credited to the logged-in retailer.

**Distributor layer (manuf → distributor → retailer).** `distributors` is a manufacturer-scoped entity for **tracking/attribution only** — no login, no wallet, no points. A retailer optionally links to one via `retailers.distributor_id`. Each scan denormalizes `points_ledger.distributor_id` at scan time (point-in-time, like `region`), so reassigning a retailer never rewrites history. `POST /retailers/import` bulk-creates retailers from CSV text (sent as JSON, no `python-multipart`): a `distributor` column find-or-creates the distributor by name (`_find_or_create_distributor`) and links it; retailer logins are auto-created via the shared `_assign_retailer_login`. The dashboard `by_distributor` rollup sums the *retailers'* scans/points grouped by distributor — never points held by the distributor itself.

**The wallet ledger.** `points_ledger` is a typed transaction log (`entry_type`: `scan`, `gift_redeem`, `refund`, `adjustment`, `transfer`). A retailer's **balance = SUM(points)** across all entries; **scan analytics filter `entry_type='scan'`** (dashboard, claims, region/product aggregates). When adding a balance-changing feature, write a ledger row rather than mutating a balance field.

**Points are frozen at generation.** `qr_batches.points_per_code` is captured when codes are generated, so reprinting/old stickers keep their promised value even if the product's `loyalty_points` later change. Schemes add a time-bound bonus on top at scan time; the most generous active scheme covering the product wins (no stacking), and the base/bonus split + paying scheme are recorded on the ledger row.

**Parent/child QR (boxes).** `qr_codes` rows are children by default; if `items_per_box` is set at generation, parent (box) codes are created with children pointing at them via `parent_token`. Scanning a parent registers all still-unredeemed children at once and sums their points.

**QR payload.** Each code encodes `{QR_BASE_URL}/{token}` (default `/web/scan`); set `QR_BASE_URL` to the deployed HTTPS origin before any production print run, or printed codes point at the wrong host. The 6-char `manual_code` is the typed fallback for damaged stickers. The token is a `uuid4().hex` lookup key — opaque, unguessable, and validated server-side (unknown → 404), so tampering with the URL can't corrupt anything; `scan.html` cosmetically rewrites the address bar to `/web/scan` after reading it.

**Retailer location & the map.** Two layers, distinct on purpose: (1) the **retailer's shop pin** — `retailers.lat/lng` + `location_source` (`city` = resolved from the typed region via `geo.coords_for`; `gps` = exact, locked on the first scan that shares location and never moved after). `region` is **optional** at registration; if blank, the first GPS scan reverse-geocodes to the nearest known city via `geo.nearest_city` (offline haversine over `CITY_COORDS`, no external geocoder) and backfills `region`. (2) **Per-scan location** — `points_ledger.lat/lng`, captured client-side **once per webview session** (`sessionStorage`, low-accuracy/fast, reused for every scan that session) and sent with `POST /scan`. The dashboard `map_points` plots scan *events* (bucketed ~110m, weighted by count), falling back to the shop pin for scans with no location. Geolocation needs a secure context (HTTPS/localhost) and is unreliable when auto-fired on mobile — the scan result screen shows the capture status and a tap-to-share button.

**Panel ↔ API.** `panel/src/api.js` is the only fetch layer: dev hits the Vite proxy (`/api` → `:8000`), production is same-origin (`/panel` served by the API). Manufacturer session token lives in `localStorage` (`vl_token`); retailer webviews use `vl_rtoken`. Navigation is a single top-right **burger menu** (`App.jsx`) listing the tabs + Log out. Every points-changing action (adjust/transfer/approve/reject; gift claim in the webview) is gated by a themed confirmation dialog — in the panel via the promise-based `useConfirm()` (`panel/src/confirm.jsx`, mounted by `ConfirmProvider` in `main.jsx`). The panel renders manufacturer tabs (Dashboard with a Leaflet India scan map — clustered via `leaflet.markercluster`, Customers, Distributors, Products, Schemes, Gifts, Claims, Redemptions) or, for super admin, the Manufacturers tab.

## Deployment

`Dockerfile` builds the panel then runs the API serving everything (`/`, `/panel`, `/web/*`). Render/Neon: set `DATABASE_URL` (Neon pooled string) and `QR_BASE_URL=https://HOST/web/scan`. The container creates/migrates tables on boot but never seeds — data persists across deploys. See `DEPLOY.md`.

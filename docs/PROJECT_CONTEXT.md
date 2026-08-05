# Project Context — Vastra Loyalty Program

A one-stop orientation to what this project is, who it serves, how it's built, and
where it stands. For deeper detail see the companion docs linked at the end.

**Status:** Live in production on Render + MySQL (AWS RDS) with real data.
**Last updated:** 2026-08-05.

---

## 1. What it is

A **multi-tenant loyalty-program backend** for the VastraApp ecosystem. The market
flow is **manufacturer → distributor → retailer**:

- **Manufacturers** (textile makers) generate QR codes in the **loyalty admin
  panel** — picking from their Vastra-catalog products — and print them on
  product/box stickers.
- **Retailers** (shops) scan those codes in **YourApp** when they receive stock,
  earning loyalty **points** they later redeem for **gifts**.
- Manufacturers get analytics on who is selling what, where, and through which
  distributor.

One FastAPI service serves three surfaces from a single container:

| Surface | Path | Audience |
|---|---|---|
| **REST API** (`app/`) | `/…`, docs at `/docs` | source of truth for all clients |
| **React admin panel** (`panel/`, built to `panel/dist`) | `/panel` | manufacturers + super admin |
| **Plain-HTML webview pages** (`app/web/`) | `/web/*` | retailers (inside YourApp), manufacturers (Vastra) |

## 2. Who uses it (principals)

- **Super admin** — creates manufacturer accounts; owns no catalog data.
- **Manufacturer** — manages products, schemes, gifts, retailers, distributors;
  generates/prints QR; sees analytics, claims, redemptions.
- **Retailer** — logs into the webview using shop username + default `<username>123` password, undergoes mandatory password change on first login (`must_change=1`), scans codes, sees wallet, redeems gifts, and can update password via the burger menu.
- **Distributor** — *not a login.* A tracking/attribution entity only (see below).

## 3. Core concepts

- **Points & the wallet ledger.** `points_ledger` is a typed transaction log
  (`scan`, `gift_redeem`, `refund`, `adjustment`, `transfer`, `scan_reversed`,
  `reversal`). A retailer's
  **balance = SUM(points)**; scan analytics filter `entry_type='scan'`. Always add
  a ledger row rather than mutating a balance. A manufacturer can **reverse** a
  scan credited to the wrong retailer (`POST /scans/reverse`): the scan rows flip
  to `scan_reversed`, negative `reversal` rows deduct the exact credited points,
  and the code is re-enabled for the rightful retailer to rescan.
- **QR codes.** Each encodes a `{QR_BASE_URL}/{token}` URL; the token is a random,
  opaque `uuid4`. A 6-char `manual_code` is the typed fallback. **Points are frozen
  per batch at generation**, so old stickers keep their promised value. Box (parent)
  codes register all their child items in one scan — and the Claims view collapses
  that box back into a single `📦 Box · N items` row (grouped at query time on
  `COALESCE(parent_token, token)`), so a box scan doesn't flood the list.
- **Products: the manufacturer imports their own catalog as CSV.** Loyalty
  does not pull products from Vastra (`get-design-ids` returns no design
  *name*). The catalog lives in `product_points` where `source='import'`
  (`POST /catalog/products/import`), and loyalty stores a
  **reference** (`product_external_id`) + immutable **snapshot**
  (`product_name`/`product_sku`) on `qr_batches` and `points_ledger`. The
  manufacturer's points-per-scan value is loyalty's own data (`product_points`
  table), set/edited from the panel and merged onto Vastra's list at read
  time. Product CRUD/import is **removed**; `GET /products` and
  `scheme_products` remain only for legacy local rows. See
  `docs/integration/PRODUCT_INTEGRATION.md`.
- **Schemes.** Time-bound bonus points on top of base, optionally scoped to
  products; the most generous active scheme wins (no stacking).
- **Gifts & redemptions.** Retailers claim gifts (points deducted, proof reference
  issued); manufacturers approve (hand over) or reject (auto-refund).
- **Distributors.** A manufacturer-scoped layer between manufacturer and retailer,
  for **tracking/attribution only** — **no login, no wallet, no points of their
  own.** A retailer optionally links to one; each scan records the distributor at
  scan time (point-in-time). The dashboard rolls up each distributor's *retailers'*
  scans/points.
- **Location.** Two layers: the retailer's **shop pin + address** (refreshed from
  the latest scan, see §5) and **per-scan coordinates** on the ledger (for the map).
  Geocoding city↔coords is **offline** (`app/geo.py` `CITY_COORDS`); the precise
  street address uses free OpenStreetMap **Nominatim**, best-effort.
- **Confirmations.** Every points-changing action (claim, transfer, adjust,
  approve/reject) requires a themed confirmation dialog first.

## 4. Feature surface (current)

**Manufacturer panel** (`/panel`, top-right burger menu):
Dashboard (two stat rows — funnel totals + redemption requests; region +
by-distributor tables; clustered India scan map; and a **QR analytics** section
with a year selector + month-wise generation and generated-vs-scanned bar charts),
Customers (retailers — with assign-distributor, per-row map link, **Import CSV**),
Distributors (**Import CSV**), Products (Vastra-sourced list, per-product
points editable inline, **Generate QR** as an in-panel modal), Schemes,
Gifts, Claims, Redemptions. Super admin sees a
Manufacturers tab instead. Every data tab has an **Export CSV** button
(client-side download, `panel/src/utils/csv.js`).

**Retailer webview** (`/web`, shared burger-menu nav — Home/Scan/Reward
shop/Claims history/Log out): home/login, **scan** (camera + manual code, with a
location-verification popup; a count-up + confetti animation on success and
auto-camera on "Scan another"), rewards **shop**, **claims** history.

**Bulk import (CSV-as-JSON, no file-upload dependency).** Four lists import:
`/retailers/import` (auto-logins + find-or-create distributor; dedupes on
phone), `/distributors/import`, `/catalog/products/import` (every column the
file has beyond name/code/points is kept verbatim and shown in the panel) and
`/gifts/import`. **Headers are matched, not dictated** — each import resolves
its fields against alias lists, so a list exported from the manufacturer's own
system imports as it comes: `Mobile` → phone, `city` → region (in preference to
`state`), `address1` → address, `retailer_points` → product points,
`Product Points` → reward cost, and a JSON-array `images` cell → the reward's
single image. Only the identity columns are required (a retailer needs a shop or
name column; a reward needs a name and points; a product needs a name and code;
a distributor needs a name). Each response echoes which of the file's columns
was read for each field, and the panel displays it.

**Delete all.** Products, Customers, Distributors and Gifts each have a bulk
clear behind a confirmation, for undoing a bad import. Rows that history
depends on are kept rather than blocking the whole operation: customers with
scans and rewards with claims survive, and the panel says so.

## 5. How location works (current behavior)

- The scan page asks for location **up front, before scanning**, via a trust-framed
  popup ("Confirm it's really you" — anti-fraud verification). High-accuracy GPS.
- **If allowed:** the shop's pin, city (`region`), and a precise reverse-geocoded
  **street address** (`retailers.address`) are **refreshed every scanning session —
  latest wins.** So a wrong registered city self-corrects to the real one. The
  Customers tab shows the address + a **"View on map"** link to the exact pin.
- **If denied/blocked/unavailable:** scanning is **not blocked** — the user taps the
  ✕ to close and the scan falls back to the retailer's **registered city** (shown in
  the Claims view). No one is locked out of earning.
- The dashboard map plots per-scan events, **clustered** (`leaflet.markercluster`)
  with zoom to street level.

## 6. Tech & architecture

- **Backend:** Python 3.12+, FastAPI, Pydantic v2, Uvicorn. PDF/QR via `reportlab`,
  `qrcode`.
- **Database — dual backend** (`app/database.py`): MySQL when `DATABASE_URL` is
  set, SQLite otherwise. Code is written in **SQLite style everywhere** (`?`
  placeholders, `cur.lastrowid`, `datetime('now')`); a `_PGConn` adapter translates
  to PyMySQL. Schema evolution is **additive & idempotent** — new tables in
  `SCHEMA`, new columns in `_MIGRATIONS`, applied by `migrate()` on every startup.
  **Never reseed/drop the production DB.** (Gotchas: no `;` inside `SCHEMA` comments; no `%` literals in SQL; `VARCHAR(n)` not `TEXT` for any indexed column.)
- **Auth:** opaque bearer tokens; two principals (`auth_tokens` for
  manufacturers/admin, `retailer_tokens` for retailers); PBKDF2 passwords. Retailer
  logins are auto-created from the shop name. **Single active session** — a new
  login (password or SSO) deletes the account's prior tokens, so one token per
  user. **Emergency lockout** — `manufacturers.blocked`/`retailers.blocked`
  (0/1, set by hand in the DB); `1` refuses login and rejects existing tokens.
- **SSO (native apps):** `POST /auth/sso/{manufacturer,retailer}` exchange a
  parent-app HS256 JWT (verified by `verify_sso_assertion`) for the same opaque
  loyalty tokens — so all other endpoints are unchanged. Principals are matched by
  `external_id` (on `manufacturers`/`retailers`) and must be pre-provisioned; the
  exchange never auto-creates. Gated by `SSO_SECRET` (unset → `503`).
- **Manufacturer OTP login (panel):** dual-mode Login screen — password, or Vastra
  mobile + OTP (`POST /auth/vastra/send-otp` → `POST /auth/vastra/verify-otp`,
  proxied to Vastra's `loyalty-signup`/`loyalty-verifyotp` via
  `app/vastra_client.py`). Matches by `external_id` (= Vastra `organization_Id`)
  or **auto-provisions** the manufacturer; stores Vastra's `access_token`
  server-side (`manufacturers.vastra_access_token`) — **nothing reads it
  today**, it is kept for a possible future catalog reconnect. Wiped on logout.
- **YourApp server-to-server scan (phone-verified):** `POST /yourapp/qr/lookup`
  (read-only code preview: product, points, `available`/`redeemed`) and
  `POST /yourapp/scan` (`phone` + `code` + optional `lat`/`lng`) are called by
  YourApp's backend with a shared secret (`X-API-Key` = env `YOURAPP_API_KEY`;
  unset → `503`) — no retailer session. The retailer is matched by registered
  **phone number** (last-10-digit match) within the scanned code's
  manufacturer; both endpoints share `/scan`'s redemption core, and the scan
  refreshes the shop pin like `POST /retailer/location`.
- **Multi-tenancy:** every owned row carries `manufacturer_id`; retailer endpoints
  derive the retailer from the token, never the body. Retailer `external_id` is
  unique per manufacturer, so a parent id can't resolve across tenants.
- **Panel:** React + Vite; `panel/src/api.js` is the only fetch layer.
- **Theme:** Vastra brand palette (blue `#0191D0`, dark blue `#1D466F`, coral
  `#FB624B`, text `#112134`, light base; green/amber kept for approved/pending) in
  Helvetica. Defined as CSS variables in `panel/src/styles.css` and mirrored in
  each `app/web/*.html` `:root`. QR codes stay black/white.

## 7. Deployment & ops

- **Render** Docker web service (`vastra-loyalty.onrender.com`, free tier — spins
  down on idle, ~50s cold start), **auto-deploys from GitHub `main`**.
- **MySQL** (AWS RDS) holds production data (`DATABASE_URL`). Tables are
  created/migrated on boot; the app **never seeds**.
- `seed.py` is destructive (local/initial only) and does **not** run `_MIGRATIONS`.
- **Env vars:** `QR_BASE_URL` (QR payload origin), `DATABASE_URL` (MySQL),
  and optionally `SSO_SECRET` + `SSO_ISSUERS`/`SSO_AUDIENCE`/`SSO_MAX_AGE` to enable
  native-app SSO, and `YOURAPP_API_KEY` to enable the YourApp server-to-server
  scan endpoints (`/yourapp/*`).

## 8. Known gaps / backlog

- Rate limiting and scan/redeem race-condition (TOCTOU) hardening are not yet done.
- Precise address quality depends on GPS accuracy + Nominatim; the "View on map"
  link is the reliable fallback.

## 9. More detail

- **README.md** — setup, endpoints, flow.
- **CLAUDE.md** — contributor conventions (SQL style, multi-tenancy, gotchas).
- **docs/PRD.md** — product requirements. **docs/TRD.md** — technical design.
- **DEPLOY.md** — deployment/ops. **CHANGELOG.md** — dated change history.

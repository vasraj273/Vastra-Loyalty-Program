# Loyalty QR API

Multi-tenant backend for a manufacturer→retailer loyalty program in the VastraApp ecosystem. Manufacturers generate QR codes in **Vastra** (printed on product/box stickers); retailers scan them in **YourApp** to earn points and redeem gifts. One FastAPI service serves three surfaces:

- **REST API** (`app/`) — source of truth for Vastra, YourApp, and the panel. Docs at `/docs`.
- **React admin panel** (`panel/`, built to `panel/dist`, served at `/panel`) — manufacturer + super-admin UI.
- **Plain-HTML webview pages** (`app/web/`, served at `/web/*`) — the mobile UI loaded inside the Vastra/YourApp webviews.

> **Docs:** start with [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) (full orientation). Product spec in [docs/PRD.md](docs/PRD.md), technical design in [docs/TRD.md](docs/TRD.md). Contributor/architecture conventions (dual DB backend, SQL style, multi-tenancy) in **CLAUDE.md**. Deployment in **DEPLOY.md**. Recent changes in **CHANGELOG.md**.

## What it does

**Multi-tenant + login-based.** A super admin creates manufacturer accounts; every manufacturer sees only their own products, retailers, schemes, gifts, and claims. Demo logins (from `seed.py`): `admin/admin123` (super admin), `surya/surya123` (Surya Textiles), `heritage/heritage123` (Heritage Weaves). Retailer logins are auto-created as `<shop-first-word>/<that>123` (e.g. `kumar/kumar123`).

**Webview pages** (served by the API; HTTPS required for the phone camera + location). Retailer pages share a top-right **burger menu** (Home · Scan · Reward shop · Claims history · Log out):
- `/web` — retailer home / login (YourApp). A scanned deep link arrives as `/web?next=/web/scan/<token>`; the token is captured in memory and stripped from the address bar so the login URL stays clean.
- `/web/scan` — in-page camera QR scanner + 6-char manual code box → points screen (confetti + count-up animation on success; "Scan another" reopens the camera directly). Printed QRs deep-link to `/web/scan/<token>` (the token is cosmetically stripped from the address bar after it's read).
- `/web/shop` — rewards shop (redeem gifts) · `/web/claims` — retailer's claim history
- `/web/generate` — standalone manufacturer generate page (still served; the panel now generates in-page instead, see below)
- `/panel/` — full admin panel (built from `panel/dist`)

## Setup (Linux)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000        # API + webviews + built panel
```

Interactive docs: http://127.0.0.1:8000/docs · seed local demo data (wipes `qr_api.db`): `.venv/bin/python seed.py`

```bash
# panel dev (proxies /api -> :8000); build required before the API can serve /panel
npm install --prefix panel
npm run dev   --prefix panel    # http://localhost:5173
npm run build --prefix panel
```

## Admin panel

React + Vite app in `panel/`. A top-right **burger menu** holds the manufacturer tabs: **Dashboard** (two stat rows — funnel totals + redemption requests; region + by-distributor tables; clustered India map of scan locations; and a **QR analytics** section with a year selector and month-wise *generation* and *generated-vs-scanned* SVG bar charts), **Customers** (retailers), **Distributors**, **Products**, **Schemes**, **Gifts**, **Claims**, **Redemptions**. Super admin gets a **Manufacturers** tab instead. `panel/src/api.js` is the only fetch layer.

Every data tab (Customers, Distributors, Products, Reward shop, Claims, Redemptions) has an **↓ Export CSV** button (client-side download, `panel/src/utils/csv.js`). On **Products**, **Generate QR** opens an **in-panel modal** (`components/GenerateQrModal.jsx`) — generate → print PDF / save for later / browse saved batches — so the manufacturer never leaves the panel. The **Claims** tab collapses a box (parent) scan into a single `📦 Box · N items` row.

## Core flow

1. **Products** — `POST /products` with `loyalty_points` (base points awarded per scan).
2. **Retailers** — `POST /retailers` with name, shop, an **optional** city, and an optional **distributor**. A login is created automatically. The city + precise location are filled/refreshed from the retailer's scans (latest wins). **Bulk import** via an "Import CSV" button on the Customers, Distributors, and Products tabs (`/retailers/import`, `/distributors/import`, `/products/import` — products upsert by SKU and accept a flexible points column like `PointsPerScan`).
   - **Distributors** (`/distributors`) sit between manufacturer and retailer (manuf → distributor → retailer) — a tracking layer so the manufacturer sees who supplies whom. Each scan records the retailer's distributor on the ledger (locked at scan time); the dashboard rolls scans/points up by distributor. Distributors have **no login and no points of their own**.
3. **Generate** (Vastra) — `POST /qr/generate {product_id, quantity, points_per_code?, items_per_box?}` → N unique codes. Each = QR token + 6-char manual fallback (alphabet excludes 0/O/1/I). With `items_per_box`, parent (box) codes wrap children. Points are **frozen per batch** at generation.
4. **Save / print** — `POST /qr/batches/{id}/save`; `GET /qr/batches/{id}/print` → A4 PDF (QR + product + manual code). Saved batches print any time.
5. **Scan** (YourApp) — `POST /scan {code, lat?, lng?}`. The retailer comes from the auth token, never the body. `code` accepts the QR token or manual code (case/dash/space insensitive). One-time redemption; awards batch points (+ best active scheme bonus) and logs a `points_ledger` row with product, region, and the scan's GPS. Scanning a box parent registers all its children at once. Duplicate → `409`.
6. **Track** (panel) — `GET /analytics/dashboard` (totals incl. redemption-request counts, by region/product/distributor, top retailers, map points, and `by_month` generation-vs-scan series). Wallet/history via `/retailer/wallet`. `GET /claims` groups box scans into one row each; every data tab exports to CSV.

## How points & location work

- **Wallet ledger.** `points_ledger` is a typed log (`scan`, `gift_redeem`, `refund`, `adjustment`, `transfer`). A retailer's balance = `SUM(points)`; scan analytics filter `entry_type='scan'`.
- **Confirmations.** Every action that changes a balance — redeem, transfer, manual adjust, approve/reject — shows a confirmation dialog before committing (scanning to earn is exempt).
- **Schemes.** Base points always apply; a scheme adds a time-bound bonus on top. Overlapping schemes don't stack — the most generous active one covering the product wins. The ledger stores the base/bonus split and the paying scheme.
- **Location.** Scanning asks for location up front (a trust-framed verification popup). When allowed, the retailer's **shop pin, city, and precise street address refresh from the latest scan** (latest wins — a wrong registered city self-corrects), shown in the Customers tab with a "View on map" link. Each scan also records its own GPS, so the dashboard map clusters *where scans actually happen*. If location is denied/blocked, scanning is **not blocked** — it falls back to the retailer's registered city (shown in Claims).

See `/docs` for the full, authoritative endpoint list.

## Design decisions

- **QR contains only a token URL** (`{QR_BASE_URL}/{token}`), not product/retailer data. The retailer is unknown at print time; all detail is joined server-side at scan. The token is a random `uuid4` — opaque, unguessable, validated server-side (so URL tampering just yields a 404).
- **Points frozen per batch** — printed stickers keep their promised value even if the product's points change later.
- **Retailer derived from the auth token** at scan time, never from the request body, so points can only be credited to the logged-in retailer.
- **Offline geocoding** — city↔coordinates use a built-in `CITY_COORDS` table (`app/geo.py`), no external geocoding service.

## Configuration

- `QR_BASE_URL` (env) — URL prefix baked into each QR (set to the deployed HTTPS origin + `/web/scan` before any production print run).
- `DATABASE_URL` (env) — Postgres/Neon connection string; falls back to local SQLite `qr_api.db` when unset. The app creates/migrates tables on boot but **never seeds**.
- `SSO_SECRET` (env) — shared HMAC secret enabling native-app **SSO** (see below). When unset, the SSO endpoints are inert (`503`); password login is unaffected. Optional companions: `SSO_ISSUERS` (default `vastra,yourapp`), `SSO_AUDIENCE` (default `loyalty`), `SSO_MAX_AGE` (default `120` seconds).

## Native app SSO

Native Vastra/YourApp builds can skip a second login. The parent backend (which already authenticated the user) mints a short-lived **HS256 JWT** and the app exchanges it for a normal loyalty token:

- `POST /auth/sso/manufacturer` — assertion `{iss, aud:"loyalty", role:"manufacturer", sub:"<vastra manufacturer external_id>", iat, exp≤120s}` → same body as `/auth/login`.
- `POST /auth/sso/retailer` — assertion adds `manufacturer_external_id` and `sub:"<yourapp retailer external_id>"` → same body as `/auth/retailer/login`.

Principals are matched by **`external_id`** and must already be **provisioned** (manufacturers imported by Vastra; retailers created/imported by their manufacturer with `external_id` set — `POST /retailers` and the `/retailers/import` CSV both accept it). The exchange never auto-creates accounts; unknown/cross-tenant principals get `403`, bad/expired assertions `401`. After the exchange the app is an ordinary bearer-token client — every other endpoint is unchanged.

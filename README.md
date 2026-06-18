# Loyalty QR API

Multi-tenant backend for a manufacturer→retailer loyalty program in the VastraApp ecosystem. Manufacturers generate QR codes in **Vastra** (printed on product/box stickers); retailers scan them in **YourApp** to earn points and redeem gifts. One FastAPI service serves three surfaces:

- **REST API** (`app/`) — source of truth for Vastra, YourApp, and the panel. Docs at `/docs`.
- **React admin panel** (`panel/`, built to `panel/dist`, served at `/panel`) — manufacturer + super-admin UI.
- **Plain-HTML webview pages** (`app/web/`, served at `/web/*`) — the mobile UI loaded inside the Vastra/YourApp webviews.

> For contributor/architecture detail (dual DB backend, SQL conventions, multi-tenancy rules), see **CLAUDE.md**. For deployment, see **DEPLOY.md**. Recent changes are in **CHANGELOG.md**.

## What it does

**Multi-tenant + login-based.** A super admin creates manufacturer accounts; every manufacturer sees only their own products, retailers, schemes, gifts, and claims. Demo logins (from `seed.py`): `admin/admin123` (super admin), `surya/surya123` (Surya Textiles), `heritage/heritage123` (Heritage Weaves). Retailer logins are auto-created as `<shop-first-word>/<that>123` (e.g. `kumar/kumar123`).

**Webview pages** (served by the API; HTTPS required for the phone camera + location):
- `/web` — retailer home / login (YourApp)
- `/web/scan` — in-page camera QR scanner + 6-char manual code box → points screen. Printed QRs deep-link to `/web/scan/<token>` (the token is cosmetically stripped from the address bar after it's read).
- `/web/shop` — rewards shop (redeem gifts) · `/web/claims` — retailer's claim history
- `/web/generate` — manufacturer: pick product → quantity → generate → print PDF
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

React + Vite app in `panel/`. Manufacturer tabs: **Dashboard** (stats, region table, interactive India map of scan locations), **Customers** (retailers), **Products**, **Schemes**, **Gifts**, **Claims**, **Redemptions**. Super admin gets a **Manufacturers** tab instead. `panel/src/api.js` is the only fetch layer.

## Core flow

1. **Products** — `POST /products` with `loyalty_points` (base points awarded per scan).
2. **Retailers** — `POST /retailers` with name, shop, and an **optional** city. A login is created automatically. If the city is left blank, it's filled in from the retailer's first scan location (reverse-geocoded to the nearest known city).
3. **Generate** (Vastra) — `POST /qr/generate {product_id, quantity, points_per_code?, items_per_box?}` → N unique codes. Each = QR token + 6-char manual fallback (alphabet excludes 0/O/1/I). With `items_per_box`, parent (box) codes wrap children. Points are **frozen per batch** at generation.
4. **Save / print** — `POST /qr/batches/{id}/save`; `GET /qr/batches/{id}/print` → A4 PDF (QR + product + manual code). Saved batches print any time.
5. **Scan** (YourApp) — `POST /scan {code, lat?, lng?}`. The retailer comes from the auth token, never the body. `code` accepts the QR token or manual code (case/dash/space insensitive). One-time redemption; awards batch points (+ best active scheme bonus) and logs a `points_ledger` row with product, region, and the scan's GPS. Scanning a box parent registers all its children at once. Duplicate → `409`.
6. **Track** (panel) — `GET /analytics/dashboard` (totals, by region/product, top retailers, map points). Wallet/history via `/retailer/wallet`.

## How points & location work

- **Wallet ledger.** `points_ledger` is a typed log (`scan`, `gift_redeem`, `refund`, `adjustment`, `transfer`). A retailer's balance = `SUM(points)`; scan analytics filter `entry_type='scan'`.
- **Schemes.** Base points always apply; a scheme adds a time-bound bonus on top. Overlapping schemes don't stack — the most generous active one covering the product wins. The ledger stores the base/bonus split and the paying scheme.
- **Location.** The retailer's **shop pin** locks to exact GPS on the first scan that shares location (and never moves). Separately, **each scan records its own GPS** (captured once per session in the browser, reused for that session), so the dashboard map shows *where scans actually happen* over time. Location is optional/graceful — scans still work if it's denied.

See `/docs` for the full, authoritative endpoint list.

## Design decisions

- **QR contains only a token URL** (`{QR_BASE_URL}/{token}`), not product/retailer data. The retailer is unknown at print time; all detail is joined server-side at scan. The token is a random `uuid4` — opaque, unguessable, validated server-side (so URL tampering just yields a 404).
- **Points frozen per batch** — printed stickers keep their promised value even if the product's points change later.
- **Retailer derived from the auth token** at scan time, never from the request body, so points can only be credited to the logged-in retailer.
- **Offline geocoding** — city↔coordinates use a built-in `CITY_COORDS` table (`app/geo.py`), no external geocoding service.

## Configuration

- `QR_BASE_URL` (env) — URL prefix baked into each QR (set to the deployed HTTPS origin + `/web/scan` before any production print run).
- `DATABASE_URL` (env) — Postgres/Neon connection string; falls back to local SQLite `qr_api.db` when unset. The app creates/migrates tables on boot but **never seeds**.

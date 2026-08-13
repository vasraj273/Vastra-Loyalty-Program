# Loyalty QR API

Multi-tenant backend for a manufacturer→retailer loyalty program in the VastraApp ecosystem. Manufacturers generate QR codes in the **loyalty admin panel** (catalog imported from the manufacturer's own CSV, printed on product/box stickers); retailers scan them in **YourApp** to earn points and redeem gifts. One FastAPI service serves three surfaces:

- **REST API** (`app/`) — source of truth for Vastra, YourApp, and the panel. Docs at `/docs`.
- **React admin panel** (`panel/`, built to `panel/dist`, served at `/panel`) — manufacturer + super-admin UI.
- **Plain-HTML webview pages** (`app/web/`, served at `/web/*`) — the mobile UI loaded inside the Vastra/YourApp webviews.

> **Docs:** start with [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) (full orientation). Product spec in [docs/PRD.md](docs/PRD.md), technical design in [docs/TRD.md](docs/TRD.md). Contributor/architecture conventions (dual DB backend, SQL style, multi-tenancy) in **CLAUDE.md**. Deployment in **DEPLOY.md**. Recent changes in **CHANGELOG.md**.

## What it does

**Multi-tenant + login-based.** A super admin creates manufacturer accounts; every manufacturer sees only their own products, retailers, schemes, gifts, and claims. Demo logins (from `seed.py`): `admin/admin123` (super admin), `surya/surya123` (Surya Textiles), `heritage/heritage123` (Heritage Weaves). Retailer logins are auto-created as `<shop-first-word>/<that>123` (e.g. `kumar/kumar123`).

> **The panel's login screen is Vastra mobile + OTP only.** `POST /auth/login` still works (and is the only way a super admin can get a token) but has no UI. To open `/panel` locally against a seeded DB, call `POST /auth/login` for a token and put it in `localStorage` as `vl_token`, with `vl_user` = `{display_name, username, is_admin}`. The retailer webviews still take their own logins normally.

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
cp .env.example .env                              # then fill in DATABASE_URL etc.
.venv/bin/uvicorn app.main:app --port 8000 --env-file .env   # API + webviews + built panel
```

> **`--env-file .env` is not optional.** This app has **no dotenv loader** — nothing in the code opens `.env`. Without the flag, `DATABASE_URL` is `None`, `IS_MYSQL` is `False`, and the server silently runs on local SQLite (`qr_api.db`) even though `.env` is sitting right there with a MySQL URL in it. See [Configuration](#configuration) for the full rule (it also affects `seed.py` and pytest).

Interactive docs: http://127.0.0.1:8000/docs · seed local demo data (wipes `qr_api.db`): `.venv/bin/python seed.py`

```bash
# panel dev (proxies /api -> :8000); build required before the API can serve /panel
npm install --prefix panel
npm run dev   --prefix panel    # http://localhost:5173
npm run build --prefix panel
```

## Admin panel

React + Vite app in `panel/`. A top-right **burger menu** holds the manufacturer tabs: **Dashboard** (two stat rows — funnel totals + redemption requests; region + by-distributor tables; clustered India map of scan locations; and a **QR analytics** section with a year selector and month-wise *generation* and *generated-vs-scanned* SVG bar charts), **Customers** (retailers), **Distributors**, **Products**, **Schemes**, **Gifts**, **Claims**, **Redemptions**. Super admin gets a **Manufacturers** tab instead. `panel/src/api.js` is the only fetch layer.

**Every tab's toolbar is the same three parts** (`components/Toolbar.jsx`): pill buttons for the actions worth a permanent slot (Import CSV; plus Transfer points on Customers and Generate QR on Products), an overflow **⋮** at the far right (Export CSV, Sample CSV, Delete all — each hidden while the list is empty), and a circular **+** button bottom-right that opens the tab's add form. Exports are client-side downloads (`panel/src/utils/csv.js`); the four importable lists (Products, Customers, Distributors, Gifts) also offer a downloadable sample file and a **Delete all**, both behind a confirm. Empty tabs render a shared `EmptyState` card saying what to do next rather than a header-only table.

**Products** lists the manufacturer's **CSV-imported catalog** (searchable by name or code, client-paginated; points-per-scan editable inline); **Generate QR** opens an **in-panel modal** (`components/GenerateQrModal.jsx`) — pick a product, set points, generate → print / save for later / browse saved batches — so the manufacturer never leaves the panel. The sticker sheet is built **in the browser** (`utils/stickerPdf.js`). The **Claims** tab collapses a box (parent) scan into a single `📦 Box · N items` row.

## Core flow

1. **Products** — `GET /catalog/products` returns the manufacturer's **CSV-imported** catalog (`{products, columns, source}`; every column of their own file is preserved). `POST /catalog/products/import` takes the CSV as JSON with `mode: upsert|replace` — a product **name** and **code** are the only required columns and headers are matched, not dictated; `PUT /catalog/products/{external_id}/points` edits points, `DELETE /catalog/products[/{external_id}]` clears one or all. Vastra's product API is **not** a catalog source (it returns no product names); legacy product CRUD is removed. See [docs/integration/PRODUCT_INTEGRATION.md](docs/integration/PRODUCT_INTEGRATION.md).
2. **Retailers** — `POST /retailers` with name, shop, an **optional** city, and an optional **distributor**. A login is created automatically. The city + precise location are filled/refreshed from the retailer's scans (latest wins). **Bulk import** via an "Import CSV" button on the Customers and Distributors tabs (`/retailers/import`, `/distributors/import`).
   - **Distributors** (`/distributors`) sit between manufacturer and retailer (manuf → distributor → retailer) — a tracking layer so the manufacturer sees who supplies whom. Each scan records the retailer's distributor on the ledger (locked at scan time); the dashboard rolls scans/points up by distributor. Distributors have **no login and no points of their own**.
3. **Generate** (panel) — `POST /qr/generate {product_external_id, product_name, product_sku, points_per_code, quantity, items_per_box?}` → N unique codes. Each = QR token + 6-char manual fallback (alphabet excludes 0/O/1/I). With `items_per_box`, parent (box) codes wrap children. Points are **frozen per batch** at generation. The manufacturer picks the product and sets the points value in the panel — no more Vastra-app/server-to-server call for this.
4. **Save / print** — `POST /qr/batches/{id}/save`. The A4 sticker sheet (QR + product + manual code) is rendered **in the browser** by `panel/src/utils/stickerPdf.js` from the codes the API returns; saved batches re-print any time via `GET /qr/batches/{id}`. The server-rendered `GET /qr/batches/{id}/print` still exists for direct API callers — the panel stopped using it because a 2,000-sticker PDF is 10.3 MB, past Lambda's 6 MB buffered response cap, where the same batch as JSON is ~180 KB.
5. **Scan** (YourApp) — `POST /scan {code, lat?, lng?}`. The retailer comes from the auth token, never the body. `code` accepts the QR token or manual code (case/dash/space insensitive). One-time redemption; awards batch points (+ best active scheme bonus) and logs a `points_ledger` row with product, region, and the scan's GPS. Scanning a box parent registers all its children at once. Duplicate → `409`.
   - **Server-to-server variant** — YourApp's backend can scan on a retailer's behalf without any retailer session: `POST /yourapp/scan {phone, code, lat?, lng?}` (auth: `X-API-Key` = `YOURAPP_API_KEY`). The retailer is matched by their registered **phone number** (last 10 digits) within the scanned code's manufacturer. `POST /yourapp/qr/lookup {code}` previews a code (product, points, `qrStatus: available|redeemed`) without redeeming, and `POST /yourapp/points {phone}` returns just a balance. Every `/yourapp/*` response — success or failure — carries a boolean **`status`** (did the call work), so YourApp can tell "no data" from "the API is down" without reading the HTTP code; the codes themselves are unchanged. See [docs/integration/YOURAPP_SCAN_API.md](docs/integration/YOURAPP_SCAN_API.md).
6. **Track** (panel) — `GET /analytics/dashboard` (totals incl. redemption-request counts, by region/product/distributor, top retailers, map points, and `by_month` generation-vs-scan series). Wallet/history via `/retailer/wallet`. `GET /claims` groups box scans into one row each; every data tab exports to CSV.

## How points & location work

- **Wallet ledger.** `points_ledger` is a typed log (`scan`, `gift_redeem`, `refund`, `adjustment`, `transfer`, `scan_reversed`, `reversal`, `import_opening`). A retailer's balance = `SUM(points)`; scan analytics filter `entry_type='scan'`, so a reversed scan and a balance carried over by a CSV import never show up as scan activity.
- **Confirmations.** Every action that changes a balance — redeem, transfer, manual adjust, approve/reject — shows a confirmation dialog before committing (scanning to earn is exempt).
- **Schemes.** Base points always apply; a scheme adds a time-bound bonus on top. Overlapping schemes don't stack — the most generous active one covering the product wins. The ledger stores the base/bonus split and the paying scheme.
- **Location.** Scanning asks for location up front (a trust-framed verification popup). When allowed, the retailer's **shop pin, city, and precise street address refresh from the latest scan** (latest wins — a wrong registered city self-corrects), shown in the Customers tab with a "View on map" link. Each scan also records its own GPS, so the dashboard map clusters *where scans actually happen*. If location is denied/blocked, scanning is **not blocked** — it falls back to the retailer's registered city (shown in Claims).

See `/docs` for the full, authoritative endpoint list.

## Design decisions

- **QR contains only a token URL** (`{QR_BASE_URL}/{token}`), not product/retailer data. The retailer is unknown at print time; all detail is joined server-side at scan. The token is a random `uuid4` — opaque, unguessable, validated server-side (so URL tampering just yields a 404).
- **Points frozen per batch** — printed stickers keep their promised value even if the product's points change later.
- **Retailer derived from the auth token** at scan time, never from the request body, so points can only be credited to the logged-in retailer.
- **Single active session** — a new login (password or SSO) deletes the account's prior tokens, so there's one token per user and signing in elsewhere signs the old device out. Logout deletes the token; there's no expiry column.
- **Emergency lockout** — a `blocked` flag (0/1) on manufacturers and retailers, flipped by hand in the DB; `1` refuses login and rejects the account's existing token on its next request (`403 Account is blocked`).
- **Offline geocoding** — city↔coordinates use a built-in `CITY_COORDS` table (`app/geo.py`), no external geocoding service.

## Configuration

### How environment variables get loaded (read this first)

**There is no dotenv loader in this project.** `python-dotenv` is not in `requirements.txt` and no code calls `load_dotenv()`. `app/database.py` reads `os.environ` directly, and `os.environ` only contains what the operating system handed the process at startup. A `.env` file on disk is just a text file — **something has to copy it into the environment first.**

That "something" differs per entry point:

| How you start it | How `.env` gets loaded | If you forget |
|---|---|---|
| **uvicorn** (the API server) | `--env-file .env` — uvicorn reads the file and sets the vars *before* importing the app | `DATABASE_URL` is `None` → `IS_MYSQL` is `False` → **silently falls back to SQLite `qr_api.db`** |
| **`seed.py`, `bootstrap_admin.py`, `import_retailers.py`, `backfill_retailer_logins.py`, pytest** | Nothing — these are plain Python, they never see uvicorn's flag. Export into the shell first:<br>`set -a; source .env; set +a` | Same: they operate on local SQLite instead of your real database |
| **Docker / AWS Lambda / Render** | **`.env` never deploys** (it's gitignored and `.dockerignore`d). Every variable must be set in the host's own configuration — Lambda function env vars, Render's env store | The feature fails closed in production while working fine locally. Classic symptom: `502 "VASTRA_API_BASE_URL is not configured"` on the panel's Vastra OTP login |

The failure mode to recognise: **the app does not error when `DATABASE_URL` is missing** — falling back to SQLite is intended behaviour for zero-setup local dev. So a missing env var looks like a working server that's writing to the wrong database. To confirm which backend you're actually on:

```bash
.venv/bin/python -c "import app.database as d; print('MySQL' if d.IS_MYSQL else 'SQLite', d.DATABASE_URL)"
# without env loaded:  SQLite None
# with env loaded:     MySQL mysql://...
```

Copy `.env.example` → `.env` to start; `.env` is gitignored and must never be committed.

### Variables

- `QR_BASE_URL` (env) — URL prefix baked into each QR (set to the deployed HTTPS origin + `/web/scan` before any production print run).
- `DATABASE_URL` (env) — MySQL connection string (`mysql://user:pass@host:3306/db?ssl=true`); falls back to local SQLite `qr_api.db` when unset. See [docs/integration/MYSQL_SETUP.md](docs/integration/MYSQL_SETUP.md). The app creates/migrates tables on boot but **never seeds**.
- `SSO_SECRET` (env) — shared HMAC secret enabling native-app **SSO** (see below). When unset, the SSO endpoints are inert (`503`); password login is unaffected. Optional companions: `SSO_ISSUERS` (default `vastra,yourapp`), `SSO_AUDIENCE` (default `loyalty`), `SSO_MAX_AGE` (default `120` seconds).
- `VASTRA_API_BASE_URL` / `VASTRA_API_KEY` (env) — Vastra's API origin + `api-key`, called server-side only (`app/vastra_client.py`) to power the panel's **Vastra OTP login** (`/auth/vastra/send-otp` → `/auth/vastra/verify-otp`, which stores the per-org Vastra `access_token` for a possible future catalog reconnect — nothing reads it today). The Products tab does **not** use Vastra: the catalog is CSV-imported. Optional `VASTRA_API_TIMEOUT` (default `10`s), `VASTRA_UDID` / `VASTRA_DEVICE_TYPE` (required Vastra device headers, fixed defaults). Unset → OTP login fails closed with `502`, which also means **nobody can sign in to `/panel`**, since OTP is its only login screen.
- `YOURAPP_API_KEY` (env) — shared secret enabling the **YourApp server-to-server** endpoints (`POST /yourapp/qr/lookup`, `POST /yourapp/scan`, `POST /yourapp/points`; header `X-API-Key`). Unset → those endpoints return `503`. Server-side only, never in a mobile build.

## Native app SSO

Native Vastra/YourApp builds can skip a second login. The parent backend (which already authenticated the user) mints a short-lived **HS256 JWT** and the app exchanges it for a normal loyalty token:

- `POST /auth/sso/manufacturer` — assertion `{iss, aud:"loyalty", role:"manufacturer", sub:"<vastra manufacturer external_id>", iat, exp≤120s}` → same body as `/auth/login`.
- `POST /auth/sso/retailer` — assertion adds `manufacturer_external_id` and `sub:"<yourapp retailer external_id>"` → same body as `/auth/retailer/login`.

Principals are matched by **`external_id`** and must already be **provisioned** (manufacturers imported by Vastra; retailers created/imported by their manufacturer with `external_id` set — `POST /retailers` and the `/retailers/import` CSV both accept it). The exchange never auto-creates accounts; unknown/cross-tenant principals get `403`, bad/expired assertions `401`. After the exchange the app is an ordinary bearer-token client — every other endpoint is unchanged.

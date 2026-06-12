# Loyalty QR API

Backend for a manufacturer→retailer loyalty program. Manufacturers generate QR codes in **Vastra** (ERP app), stickers go on delivery boxes, retailers scan them in **YourApp** on receiving the shipment and earn points. Manufacturer sees WHO bought WHICH product WHERE.

**Multi-tenant + login-based.** Super admin creates manufacturer accounts; every manufacturer sees only their own products, retailers, schemes and claims. Demo logins (from `seed.py`): `admin/admin123` (super admin), `surya/surya123` (Surya Textiles), `heritage/heritage123` (Heritage Weaves).

**Webview demo pages** (served by the API itself, for testing inside Vastra/YourApp webviews):
- `/web/generate` — manufacturer login → pick product → quantity → generate → print PDF
- `/web/scan` — retailer side: in-page camera QR scanner + 6-char manual code box → points screen. Printed QRs also deep-link straight to `/web/scan/<token>`.
- `/panel/` — the full admin panel (login-based), served from `panel/dist` after `npm run build`.

See `DEPLOY.md` for putting the demo on a free HTTPS host (needed for phone cameras).

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --port 8000
```

Interactive docs: http://127.0.0.1:8000/docs

## Admin panel (manufacturer-only)

React + Vite app in `panel/`. Three tabs: **Dashboard** (stats, region table, interactive India map of scanning retailers), **Schemes** (active/upcoming/previous campaigns + create form), **Claims** (paginated redemption table with filters).

```powershell
# demo data (wipes qr_api.db)
.\.venv\Scripts\python seed.py
# run API (terminal 1) and panel (terminal 2)
.\.venv\Scripts\uvicorn app.main:app --port 8000
npm run dev --prefix panel    # -> http://localhost:5173
```

## Schemes / campaigns

Base points always apply on scan. A scheme adds time-bound bonus points on top (`POST /schemes`: name, description, start/end date, bonus_points, optional product_ids — empty = all products). Status (active/upcoming/previous) computed from dates. Overlapping schemes don't stack; the most generous bonus wins. The ledger stores the base/bonus split and the paying scheme.

## Flow

1. **Products** — `POST /products` with `loyalty_points` (points awarded per scan, set by manufacturer).
2. **Retailers** — `POST /retailers` with name, shop, **region** (region recorded on every scan comes from here).
3. **Generate** (Vastra) — `POST /qr/generate {product_id, quantity, points_per_code?}` → N unique codes. Each code = QR token + **6-char manual fallback code** (typed by hand if sticker damaged; alphabet excludes 0/O/1/I). Points are frozen per batch at generation.
4. **Save / print** — `POST /qr/batches/{id}/save`; `GET /qr/batches/{id}/print` → A4 PDF, each label shows QR + product + manual code (e.g. `8P6-CBB`). Saved batches printable any time.
5. **Scan** (YourApp) — `POST /scan {code, retailer_id}`. `code` accepts the QR token or the manual code (case/dash/space insensitive). One-time redemption; awards batch points to retailer; logs retailer + region + product + timestamp in the points ledger. Duplicate scan → `409`.
6. **Track** (Vastra) — `GET /analytics/summary` (totals, by product / region / retailer), `GET /analytics/scans` (raw events, filter by `product_id`, `retailer_id`, `region`, `from`, `to`). `GET /retailers/{id}/points` for balance + history.

## Endpoints

| Method | Path | App | Purpose |
|---|---|---|---|
| POST | `/products` | Vastra | Register product + loyalty points |
| GET | `/products` | Vastra | List products |
| POST | `/retailers` | Vastra | Register retailer (name, shop, region) |
| GET | `/retailers` | Vastra | List retailers |
| GET | `/retailers/{id}/points` | both | Points balance + history |
| POST | `/qr/generate` | Vastra | Generate N codes (QR + manual) for a product |
| GET | `/qr/batches` | Vastra | List batches (`?status=pending\|saved`) |
| GET | `/qr/batches/{id}` | Vastra | Batch detail incl. redemption state |
| POST | `/qr/batches/{id}/save` | Vastra | Mark batch saved |
| GET | `/qr/batches/{id}/print` | Vastra | Printable A4 PDF |
| DELETE | `/qr/batches/{id}` | Vastra | Discard batch |
| GET | `/qr/codes/{token}/image` | both | Single QR as PNG |
| POST | `/scan` | YourApp | Redeem by QR token or manual code, award points |
| GET | `/analytics/scans` | Vastra | Raw scan events (who/what/where filters) |
| GET | `/analytics/summary` | Vastra | Aggregates by product/region/retailer |

## Design decisions

- **QR contains only a token URL** (`{QR_BASE_URL}/{token}`), not product/retailer data. Retailer is unknown at print time; all detail is joined server-side at scan. Also prevents forged/stale payloads.
- **Points frozen per batch** — printed boxes keep their promised value even if the product's points change later.
- **Region from retailer profile**, not GPS.
- **Auth is not wired yet.** Integration point: Vastra/YourApp authenticate (ERP auth or API keys), and `/scan` should take `retailer_id` from the session, not the body. Onboarding flow TBD.

## Configuration

- `QR_BASE_URL` (env) — URL prefix in each QR, default `https://loyalty.example.com/scan`.
- Storage: SQLite at `qr_api.db`. Batch quantity cap: 10,000.

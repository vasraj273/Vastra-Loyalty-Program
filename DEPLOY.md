# Deploying the demo

One container serves everything: API + admin panel (`/panel`) + webview pages (`/web/generate`, `/web/scan`). HTTPS is required for the phone camera on the scan page — both hosts below give it automatically.

## Option A: Render (free tier, easiest)

1. Push this folder to a GitHub repo.
2. https://render.com → New → Web Service → connect the repo.
3. Environment: **Docker**. Region: Singapore (closest to India).
4. Add environment variable:
   - `QR_BASE_URL` = `https://<your-service>.onrender.com/web/scan`
   - `SSO_SECRET` = a long random string — only needed to enable native-app SSO (see below); omit for a plain demo.
   - `VASTRA_API_BASE_URL` / `VASTRA_API_KEY` — only needed to power the panel's product picker (see "Vastra product catalog" below); omit for a plain demo (the Products tab shows a 502 until set).
5. Deploy. First boot auto-seeds demo data (`admin/admin123`, `surya/surya123`, `heritage/heritage123`).

Note: free tier sleeps after idle (first request takes ~30s) and the SQLite file resets on redeploy — fine for a demo, not for production.

## Option B: Railway

1. Push to GitHub → https://railway.app → New Project → Deploy from repo (Dockerfile auto-detected).
2. Set `QR_BASE_URL` = `https://<your-app>.up.railway.app/web/scan`.
3. Generate a public domain in Settings → Networking.

## Demo URLs (replace host)

| What | URL |
|---|---|
| Admin panel (login) | `https://HOST/panel/` |
| Generate webview (Vastra) | `https://HOST/web/generate` |
| Retailer home/login (YourApp) | `https://HOST/web` |
| Scan webview (YourApp) | `https://HOST/web/scan` (login required) |
| Rewards shop (YourApp) | `https://HOST/web/shop` (login required) |
| API docs | `https://HOST/docs` |

## Demo script (5 min)

1. **Super admin**: log into panel as `admin/admin123` → Manufacturers tab → create a manufacturer login live.
2. **Manufacturer**: log out, log in as `surya/surya123` → dashboard with map, schemes, claims (all Surya-only data; log in as `heritage` to show isolation).
3. **Generate**: in the panel, Products tab → **Generate QR** (opens an in-panel modal) → pick product → quantity 5 → Generate → Print PDF. (The standalone `/web/generate` page still works for the Vastra webview.)
4. **Scan**: scan a printed QR with the phone camera — it opens `/web/scan/<token>` directly → Redeem → count-up + confetti animation with the scheme bonus. Or open `/web/scan`, use the in-page camera / type the 6-char manual code; "Scan another" reopens the camera. The retailer pages share a burger-menu nav.
5. Back in the panel: the scan is already in Claims (a box scan shows as one `📦 Box · N items` row) and on the map. Every data tab has an **Export CSV** button.

## Database (Postgres / Neon)

The app uses Postgres when `DATABASE_URL` is set, SQLite otherwise (local dev
needs no setup). On Render, set `DATABASE_URL` to the Neon **pooled**
connection string. Data persists across deploys — the container creates
tables if missing but never auto-seeds.

Seed the demo data **once** (locally, with the env var set):

```powershell
$env:DATABASE_URL = '<neon pooled connection string>'
.\.venv\Scripts\python seed.py
```

Re-running `seed.py` wipes and refills — don't run it against a database
holding real data.

> **Note:** `seed.py` rebuilds tables from `SCHEMA` only; it does **not** run
> the column migrations in `_MIGRATIONS`. The app applies them automatically on
> the next startup (`migrate()`), so a normal deploy self-heals. But if you seed
> and then query the database directly without restarting the app, newer columns
> (e.g. `points_ledger.lat/lng`) will be missing — run `migrate()` (or just start
> the app) after seeding.

## Retailer logins (YourApp side)

Retailers log in at `/web` (the retailer home), then Scan or Rewards Shop.
Points always go to the logged-in retailer — a code can't be credited to
another shop. Demo logins are seeded (e.g. `kumar/kumar123` under Surya,
`nair/nair123` under Heritage).

Bulk-onboard real retailers from the terminal (no website button):

```powershell
$env:DATABASE_URL = '<neon pooled connection string>'
.\.venv\Scripts\python import_retailers.py sample_retailers.csv
```

CSV columns: `manufacturer_username, name, shop_name, region, phone,
username, password`. To give existing (login-less) retailers a login,
run `python backfill_retailer_logins.py`.

## Native app SSO (Vastra / YourApp)

To let native apps reach loyalty without a second login, set **`SSO_SECRET`**
(shared with the Vastra/YourApp backends). The parent backend mints a
short-lived **HS256 JWT**; the app posts it to `POST /auth/sso/manufacturer` or
`POST /auth/sso/retailer` and receives a normal loyalty token. Optional env:
`SSO_ISSUERS` (default `vastra,yourapp`), `SSO_AUDIENCE` (default `loyalty`),
`SSO_MAX_AGE` (default `120` seconds).

Provisioning is required first — the exchange never auto-creates accounts:
- **Manufacturers:** set `external_id` (the Vastra manufacturer id) when creating each manufacturer.
- **Retailers:** set `external_id` (the YourApp retailer id) via `POST /retailers` or the `external_id` column in the `/retailers/import` CSV. It is unique per manufacturer.

Unknown or cross-tenant principals get `403`; tampered/expired assertions get
`401`. If `SSO_SECRET` is unset the SSO endpoints return `503` and are otherwise
harmless. The `external_id` columns + unique indexes are added automatically on
boot (`migrate()`/`create_constraints()`), so no manual migration is needed.

## Vastra product catalog

The Products tab and QR generation read the manufacturer's product catalog
from Vastra, not from a local table. Set **`VASTRA_API_BASE_URL`** (Vastra's
product-list API origin) and **`VASTRA_API_KEY`** (credential, server-side
only — never sent to the browser) to enable it; optional `VASTRA_API_TIMEOUT`
(seconds, default `5`). Unset → `GET /vastra/products` fails closed with a
`502`. The manufacturer's per-product points value is loyalty's own data
(`product_points` table), not Vastra's — it's set/edited from the Products
tab and merged onto Vastra's list at read time. See
`docs/integration/PRODUCT_INTEGRATION.md`.

## Before real (non-demo) use

- Rotate the seeded passwords / disable seed.
- Restrict CORS origins to the real app domains.
- Set a strong `SSO_SECRET` (and keep it out of source control) if native-app SSO is used.
- Set `VASTRA_API_BASE_URL`/`VASTRA_API_KEY` once Vastra shares their real API contract (see `app/vastra_client.py` — currently a placeholder mapping).
- Rotate the Neon credentials if the connection string was shared.

## Emergency: block / unblock an account

Sessions are single-active (a new login invalidates the old token), and any
account can be frozen by hand in the DB — no deploy needed. Against Neon:

```sql
UPDATE manufacturers SET blocked = 1 WHERE username = '<user>';   -- block
UPDATE manufacturers SET blocked = 0 WHERE username = '<user>';   -- restore
UPDATE retailers     SET blocked = 1 WHERE id = <retailer_id>;    -- block a retailer
```

A blocked account can't log in, and its current token stops working on the next
request (both return `403 Account is blocked`). Set `blocked = 0` to restore.

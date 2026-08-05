# Deploying the demo

One container serves everything: API + admin panel (`/panel`) + webview pages (`/web/generate`, `/web/scan`). HTTPS is required for the phone camera on the scan page — both hosts below give it automatically.

## Option A: Render (free tier, easiest)

1. Push this folder to a GitHub repo.
2. https://render.com → New → Web Service → connect the repo.
3. Environment: **Docker**. Region: Singapore (closest to India).
> ⚠️ **`.env` is gitignored and never ships.** This app has no dotenv loader —
> locally you pass `--env-file .env` to uvicorn, but a hosted service reads
> nothing of the sort. **Every variable below must be entered in Render's own
> Environment tab.** If it isn't, the feature fails closed in production while
> working perfectly on your machine. The usual symptom is the panel's Vastra
> OTP login answering
> `502 "Vastra login service unavailable: VASTRA_API_BASE_URL is not configured"`.
> Changing a variable in Render restarts the service; no redeploy needed.

4. Add environment variable:
   - `QR_BASE_URL` = `https://<your-service>.onrender.com/web/scan`
   - `SSO_SECRET` = a long random string — only needed to enable native-app SSO (see below); omit for a plain demo.
   - `VASTRA_API_BASE_URL` / `VASTRA_API_KEY` — power the panel's **Vastra OTP login** (see below); omit for a plain demo (OTP login fails closed with a 502 until set; password login keeps working). These do **not** affect the product catalog.
   - `USE_SAMPLE_PRODUCTS` — leave unset (defaults to `0`) for a real client. Set it to `1` only for demos/testing, which makes the Products tab show three built-in demo products until the manufacturer imports their CSV.
   - `YOURAPP_API_KEY` = a long random string shared with YourApp's backend — enables the server-to-server scan endpoints (`/yourapp/qr/lookup`, `/yourapp/scan`, see "YourApp server-to-server scan" below); omit and they return `503`.
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

## Database (MySQL)

The app uses MySQL when `DATABASE_URL` is set, SQLite otherwise (local dev
needs no setup). Data persists across deploys — the container creates and
migrates tables on boot but never auto-seeds.

**Full provisioning requirements are in
[docs/integration/MYSQL_SETUP.md](docs/integration/MYSQL_SETUP.md)** — server
version, charset/collation, and the grants the app needs to run its startup
DDL. The short version: MySQL **8.0.13+**, database created with `utf8mb4` /
`utf8mb4_0900_ai_ci`, and a user with `CREATE`/`ALTER`/`INDEX`/`REFERENCES` in
addition to DML.

```
DATABASE_URL=mysql://user:pass@host:3306/vastra_loyalty?ssl=true
```

If a PostgreSQL URL is left in the environment from before the MySQL
migration, the app refuses to start and says so explicitly rather than failing
on the first request.

Seed the demo data **once** (locally, with the env var set). The MySQL path is
destructive, so it requires an explicit opt-in:

```powershell
$env:DATABASE_URL = 'mysql://user:pass@host:3306/vastra_loyalty?ssl=true'
$env:ALLOW_MYSQL = '1'
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
$env:DATABASE_URL = 'mysql://user:pass@host:3306/vastra_loyalty?ssl=true'
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

## YourApp server-to-server scan (phone-verified)

YourApp's backend can scan on behalf of a retailer without any retailer
session: set **`YOURAPP_API_KEY`** (a long random shared secret) and have
YourApp send it in the `X-API-Key` header to `POST /yourapp/qr/lookup`
(read-only preview: product, points, scanned-or-not) and `POST /yourapp/scan`
(`phone` + `code` + optional `lat`/`lng`). The retailer is matched by the
**phone number** registered in loyalty (import retailers with their YourApp
phone via the panel's Import CSV) — matching uses the last 10 digits, scoped
to the scanned code's manufacturer. Unset key → both endpoints return `503`.
Keep the key server-side only (never in a mobile app build), and rotate it by
changing the env var. See `docs/integration/API_REFERENCE.md`.

## Vastra OTP login & product catalog

Manufacturers log into the panel with **Vastra mobile + OTP**
(`/auth/vastra/send-otp` → `/auth/vastra/verify-otp`); the verify step stores
Vastra's per-org `access_token` server-side. **Nothing reads that token today**
— the product catalog is imported from the manufacturer's own CSV, not pulled
from Vastra (`get-design-ids` returns no product names). It is kept for a
future catalog reconnect. Env:
**`VASTRA_API_BASE_URL`** (Vastra's API origin, e.g. the staging
`…:3000/api/v2` host — the contract was verified live 2026-07-16),
**`VASTRA_API_KEY`** (`api-key` header; staging value `1`), optional
`VASTRA_API_TIMEOUT` (seconds, default `10`) and `VASTRA_UDID` /
`VASTRA_DEVICE_TYPE` (Vastra requires device headers; fixed defaults are
accepted). All calls are server-side only (`app/vastra_client.py`) — nothing
Vastra-related is ever sent to the browser. Unset base URL → OTP login fails
closed with a `502` (password login is unaffected). The product catalog lives
in loyalty's own `product_points` table, imported via the Products tab's
**Import CSV** button. See `docs/integration/PRODUCT_INTEGRATION.md`.

## Before real (non-demo) use

- Rotate the seeded passwords / disable seed.
- Restrict CORS origins to the real app domains.
- Set a strong `SSO_SECRET` (and keep it out of source control) if native-app SSO is used.
- Point `VASTRA_API_BASE_URL`/`VASTRA_API_KEY` at Vastra's **production** API (the implemented contract was verified against staging 2026-07-16; confirm the production origin + api-key with Vastra's team).
- Leave `USE_SAMPLE_PRODUCTS` unset (it defaults to `0`) so the Products tab prompts for a CSV import instead of listing the three built-in demo products. If a demo set it to `1`, remove it.
- Set a strong `YOURAPP_API_KEY` and share it only with YourApp's backend; make sure every retailer has their YourApp phone number imported (phone identifies the retailer on `/yourapp/scan`).
- Rotate the MySQL credentials if the connection string was shared.

## Emergency: block / unblock an account

Sessions are single-active (a new login invalidates the old token), and any
account can be frozen by hand in the DB — no deploy needed. Against MySQL:

```sql
UPDATE manufacturers SET blocked = 1 WHERE username = '<user>';   -- block
UPDATE manufacturers SET blocked = 0 WHERE username = '<user>';   -- restore
UPDATE retailers     SET blocked = 1 WHERE id = <retailer_id>;    -- block a retailer
```

A blocked account can't log in, and its current token stops working on the next
request (both return `403 Account is blocked`). Set `blocked = 0` to restore.

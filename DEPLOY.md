# Deploying the demo

One container serves everything: API + admin panel (`/panel`) + webview pages (`/web/generate`, `/web/scan`). HTTPS is required for the phone camera on the scan page — both hosts below give it automatically.

## Option A: Render (free tier, easiest)

1. Push this folder to a GitHub repo.
2. https://render.com → New → Web Service → connect the repo.
3. Environment: **Docker**. Region: Singapore (closest to India).
4. Add environment variable:
   - `QR_BASE_URL` = `https://<your-service>.onrender.com/web/scan`
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
3. **Generate**: open `/web/generate` on phone or webview → log in as surya → pick product → quantity 5 → Generate → Print PDF.
4. **Scan**: scan a printed QR with the phone camera — it opens `/web/scan/<token>` directly → pick shop → Redeem → points animation with scheme bonus. Or open `/web/scan`, use in-page camera / type the 6-char manual code.
5. Back in the panel: the scan is already in Claims and on the map.

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

## Before real (non-demo) use

- Rotate the seeded passwords / disable seed.
- Restrict CORS origins to the real app domains.
- Rotate the Neon credentials if the connection string was shared.

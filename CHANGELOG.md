# Changelog

Notable changes to the Loyalty QR API. Dates are when the change went live on
production (Render + Neon). Schema changes are additive (`_MIGRATIONS`), applied
by `migrate()` on startup — no reseed, existing data preserved.

## 2026-06-23 (dashboard expansion)

### Added
- **Second stat row on the Dashboard — redemption requests.** Three new cards:
  total redeem requests, pending requests, approved requests. Backed by new
  `redeem_total` / `redeem_pending` / `redeem_approved` counts (from `gift_claims`)
  in the `/analytics/dashboard` `totals`.
- **QR analytics charts.** A new Dashboard section with a **Year selector** and two
  themed, hand-rolled SVG bar charts (no new dependency, `panel/src/components/BarChart.jsx`):
  **Month-wise QR generation** (codes generated per month) and **Generated vs scanned**
  (grouped bars per month). Powered by a new `by_month` array
  (`{month, generated, scanned}`) on `/analytics/dashboard`, bucketed with
  `substr(created_at, 1, 7)` so it is portable across SQLite and Postgres. Each chart
  shows a per-year subtotal so the bars reconcile to a number on the card.

### Changed
- **First stat row reordered into a funnel:** Retailers · Products · Codes issued ·
  Codes scanned · Points awarded (the old "Scans" card is relabelled "Codes scanned").
- **Region-wise card no longer shows a blank row.** Scans from retailers with no
  region (region is optional at registration) are now grouped under the label
  **"Unspecified"** instead of an empty cell (`COALESCE(NULLIF(region, ''), 'Unspecified')`).

### Notes
- Cards are **all-time** totals; the QR charts are **per-month within the selected
  year**, which is why a single bar never equals an all-time card. The charts' bars
  always sum to the card totals across all years.

## 2026-06-23

### Added
- **Precise shop location + address.** When a retailer shares location it is now
  reverse-geocoded to a full street address (free OpenStreetMap Nominatim, in
  `geo.reverse_address`) and stored in the new nullable `retailers.address`
  column. The Customers "Location" column shows the address plus a Google Maps
  **"View on map"** link to the exact pin. Scan capture switched to high-accuracy
  GPS for a tighter pin.
- **CSV import for Products and Distributors.** "Import CSV" buttons on both tabs
  (matching Customers) with new `POST /products/import` and
  `POST /distributors/import`, reporting created/updated/skipped/errors via a
  shared `ImportResult` component.

### Changed
- **Shop location now updates every scan (latest wins).** Previously the pin
  locked on the first GPS scan and a registered city never corrected. Now each
  scanning session refreshes the pin, city, and address — so a wrong city (e.g.
  Surat) self-corrects to where the retailer actually scans (Ahmedabad).
- **Location asked up front, before scanning.** A trust-framed verification popup
  ("Confirm it's really you") replaces the after-the-fact capture and the "Share
  shop location" button. It is **not** a hard block: a retailer who can't grant it
  taps ✕ and the scan falls back to their registered city (shown in Claims).
- **Map dots clustered** (`leaflet.markercluster`) with street-level zoom; per-dot
  precision tightened to ~11m.

### Fixed
- **Product CSV import ignored the points column** unless it was named exactly
  `loyalty_points` — a CSV with `PointsPerScan` imported everything at 0 points.
  Points are now matched under several header aliases, and import **upserts by
  SKU** (updates an existing product instead of skipping), so re-importing a
  corrected CSV fixes existing rows with no manual editing.

### Notes
- New DB column: `retailers.address` (nullable, additive).
- Added `docs/PROJECT_CONTEXT.md` — a full project orientation/summary.

## 2026-06-19

### Added
- **Distributor tracking (manufacturer → distributor → retailer).** A new
  `distributors` table (manufacturer-scoped) plus `retailers.distributor_id` lets
  manufacturers record which distributor each retailer sits under. Distributors
  are **tracking/attribution only** — no login, no wallet, no points of their own.
  - Distributor CRUD (`/distributors`); retailer create/update/list carry and
    validate `distributor_id`.
  - Every scan records `points_ledger.distributor_id`, **locked at scan time**
    (point-in-time, like `region`) so reassigning a retailer never rewrites history.
  - **`POST /retailers/import`** — self-serve CSV upload (posted as JSON text, no
    `python-multipart` dep). Columns: `shop_name` (required), `name`, `region`,
    `phone`, `distributor`. Each retailer gets an auto-login; the distributor is
    found-or-created by name and linked. Duplicate `shop_name` rows are skipped.
  - Dashboard `by_distributor` rollup (retailers + their scans/points — the
    retailers' figures, grouped, not distributor points).
  - Panel: **Distributors** tab; Customers tab gets a per-row assign-distributor
    dropdown, a distributor column/form field, and an **Import CSV** button.
- **Confirmation dialogs on points changes.** Every action that changes a points
  balance — redeem/claim, transfer, manual adjust (+/-), and approve/reject a
  redemption — now shows a themed confirmation dialog summarizing the effect
  before it commits. Panel uses a reusable promise-based `useConfirm()`
  (`panel/src/confirm.jsx`); the retailer webview gets a matching themed dialog in
  `shop.html`. Scanning to earn is exempt.

### Changed
- **Dashboard map clustering + street zoom.** Added `leaflet.markercluster`:
  dense cities collapse into a numbered cluster bubble that splits as you zoom
  (max zoom 12 → 18). Dots became `L.marker` + `divIcon` (markercluster can't
  cluster `circleMarker`). Scan-dot bucket precision sharpened 3 → 4 decimals
  (~110m → ~11m).
- **Panel navigation → burger menu.** The crowded horizontal tab bar is replaced
  by a single top-right burger button (shows the current tab) opening a dropdown
  with all tabs + Log out; closes on outside-click/Escape, themed to match.

### Fixed
- **Postgres deploy crash.** A `;` inside the new `distributors` schema comment
  split the statement in the PG adapter's `executescript` (SQLite handled it, so
  it passed locally but crashed `init_db` on Neon). Reworded the comment and
  hardened `executescript` to strip full-line `--` comments before splitting.
  **Rule: no `;` in `SCHEMA` comments.**

### Notes
- New DB objects: `distributors` table, `retailers.distributor_id`,
  `points_ledger.distributor_id` (all nullable/additive).

## 2026-06-18

### Added
- **Per-scan GPS location.** Each scan records where it happened: `points_ledger`
  gains nullable `lat`/`lng`, captured once per webview session on the client and
  sent with `POST /scan`. The dashboard India map plots scan *events* (grouped by
  retailer + rounded coords ~110m, weighted by count), falling back to the
  retailer's shop pin for scans without a location.
- **Optional city + auto-detect.** `region` is now optional when adding a
  retailer. If left blank, the first scan that shares GPS reverse-geocodes to the
  nearest known city (`geo.nearest_city`, offline haversine over `CITY_COORDS` —
  no external geocoder) and backfills the retailer's `region`.
- **Auto-created retailer logins.** `POST /retailers` now creates a login
  automatically: username = first word of the shop name (lowercased
  alphanumerics), password = `<username>123`, with the retailer id appended on a
  clash. The creation response returns the credentials once for the panel to show.

### Changed
- **Reliable mobile location capture.** Switched to city-level accuracy
  (`enableHighAccuracy: false`, 20s timeout, cached fix) — high-accuracy GPS
  routinely timed out on phones. Transient failures now retry (only a hard
  permission denial is remembered for the session). The scan result screen shows
  the capture status and a tap-to-share button (a user gesture is the most
  reliable way to get the location prompt on mobile).
- **Clean scan URL.** After a deep-linked QR token is read, the address bar is
  cosmetically rewritten to `/web/scan` (the token is still used for the scan).

### Notes
- New DB columns: `points_ledger.lat`, `points_ledger.lng` (both nullable).
- `seed.py` rebuilds from `SCHEMA` only and does not run `_MIGRATIONS`; run
  `migrate()` (or start the app) after seeding. See DEPLOY.md.

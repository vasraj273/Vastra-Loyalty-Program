# Changelog

Notable changes to the Loyalty QR API. Dates are when the change went live on
production (Render + Neon). Schema changes are additive (`_MIGRATIONS`), applied
by `migrate()` on startup — no reseed, existing data preserved.

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

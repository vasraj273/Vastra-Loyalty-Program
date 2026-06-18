# Changelog

Notable changes to the Loyalty QR API. Dates are when the change went live on
production (Render + Neon). Schema changes are additive (`_MIGRATIONS`), applied
by `migrate()` on startup — no reseed, existing data preserved.

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

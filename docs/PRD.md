# Product Requirements Document — Vastra Loyalty Program

**Status:** Live in production · **Last updated:** 2026-08-13 · **Owner:** Vastra team

## 1. Overview

A multi-tenant loyalty platform connecting **manufacturers** (textile makers) and
their **retailers** (shops). Manufacturers print QR-coded stickers on products/boxes
in their **Vastra** app; retailers scan them in **YourApp** on receiving stock to
earn loyalty points, which they redeem for gifts. Manufacturers get visibility into
who is selling what, where, and how much.

One FastAPI backend serves three surfaces: the REST API, a React admin panel
(`/panel`), and mobile webview pages (`/web/*`) embedded in the Vastra/YourApp apps.

## 2. Problem & goals

Manufacturers ship through a long retailer network and have no reliable signal on
sell-through, regional demand, or which retailers are active. Paper/manual loyalty
schemes are unverifiable and easy to abuse.

**Goals**
- Verifiable, one-time-redeemable rewards tied to physical product (QR stickers).
- Per-manufacturer isolation (each sees only their own data).
- Actionable analytics: scans by product, region, and retailer, on a live map.
- Low-friction retailer experience (scan → points → gifts), minimal onboarding.

**Non-goals**
- Consumer-facing (end-shopper) loyalty — this is manufacturer→retailer (B2B).
- Payments/settlement. Points are non-monetary reward units.
- Inventory/ERP replacement — Vastra remains the system of record for catalog/stock.

## 3. Users / personas

| Persona | Surface | Needs |
|---|---|---|
| **Super admin** | Panel | Create manufacturer accounts; no catalog data of their own. |
| **Manufacturer** | Panel + Vastra webview | Manage products, schemes, gifts; generate/print QR; see analytics, customers, claims. |
| **Retailer** | YourApp webview | Log in, scan codes, see wallet, redeem gifts, view claim history. |

## 4. Functional requirements

### 4.1 Accounts & access
- Super admin creates manufacturer logins. Each manufacturer is fully isolated.
- Retailers are created by their manufacturer and get an **auto-generated login**
  (username = first word of shop name, password = `<username>123`). A retailer
  belongs to exactly one manufacturer.
- **Single sign-on for native apps.** Native Vastra/YourApp builds reach loyalty
  **without a second login**: the parent app exchanges a signed assertion for a
  loyalty session (`POST /auth/sso/{manufacturer,retailer}`). Users are matched by
  a parent-system **`external_id`** and must be provisioned beforehand
  (manufacturers imported by Vastra; retailers created/imported by their
  manufacturer with `external_id`) — SSO never creates accounts. The manufacturer
  web panel logs in with **Vastra mobile + OTP** (which also enables the Vastra
  product catalog; password login remains as a fallback without catalog access);
  retailer access is SSO-only in production.
- **One active session per user.** A new login (password or SSO) invalidates the
  previous token, so signing in on another device signs the first one out.
- **Emergency lockout.** An admin can disable any manufacturer or retailer by
  setting its `blocked` flag in the DB; a blocked account cannot log in and its
  existing session stops working on the next request.

### 4.2 Catalog & rewards
- **Products come from the manufacturer's own CSV** — the catalog is imported
  in the Products tab (`POST /catalog/products/import`), headers matched rather
  than dictated, and every extra column of their file is kept and displayed.
  Vastra's product API is **not** a catalog source (it returns design numbers
  but no design names). The manufacturer sets/edits each product's **base
  loyalty points** in the panel.
- **Schemes** add a time-bound bonus on top of base points (optionally scoped to
  specific products). Overlapping schemes do not stack — the most generous active
  one wins.
- **Gifts** form a rewards catalog with a points cost. Retailers claim gifts;
  manufacturers approve/reject claims, each claim carrying a proof reference.

### 4.3 QR generation & scanning
- Generate N unique codes per batch; each has a scannable QR token and a 6-char
  manual fallback code. Optional box mode wraps child items under a parent code.
- **Points are frozen per batch at generation** — reprints/old stickers keep their
  promised value even if product points later change.
- Scanning (QR token or manual code) credits the **logged-in retailer** only,
  once per code; scanning a box parent registers all its children at once.
- **YourApp in-app scanning (server-to-server):** retailers already live in
  YourApp, so they never sign up twice — the manufacturer imports them (with
  their YourApp **phone number**) via CSV, and YourApp's backend scans on
  their behalf: a preview call shows what the code is worth and whether it was
  already scanned, then the scan call credits the retailer matched by phone
  number. Protected by a shared server-side secret; a phone that isn't
  registered under the code's manufacturer is rejected.
- QR generation happens **in the panel** (a modal on the Products tab: generate →
  print PDF → save for later → browse saved batches), so the manufacturer never
  leaves the admin UI.
- In the Claims view a **box (parent) scan is shown as a single row** (`📦 Box ·
  N items`, points summed) rather than one row per child code, so a box scan does
  not flood the list. Individual scans remain one row each.

### 4.4 Location & analytics
- A retailer's **city is optional** at registration.
- Scanning asks for location **up front**, framed as a fairness/anti-fraud check
  ("confirm it's really you"). It is **not mandatory** — a retailer who can't or
  won't share it closes the popup (✕) and the scan proceeds on their registered
  city; nobody is locked out of earning.
- When location is shared, the retailer's **shop pin, city, and a precise street
  address** are refreshed from the **latest** scan (latest wins) — so a wrong
  registered city self-corrects to where they actually are. The manufacturer sees
  the address and a "View on map" link precise enough to visit the shop.
- **Each scan records its own GPS**, so the dashboard map shows where scans
  actually happen, clustered with zoom to street level.
- Dashboard shows two stat rows (funnel totals — retailers, products, codes issued,
  codes scanned, points awarded — plus redemption-request counts: total, pending,
  approved), scans by region/product, by distributor, top retailers, and the
  interactive India scan map. Scans from retailers with no region group under
  **"Unspecified"** (no blank row).
- A **QR analytics** section charts QR activity over time: a **year selector** drives
  a **month-wise QR generation** bar chart and a **generated-vs-scanned** monthly
  comparison. Stat cards are all-time; the charts are per-month within the selected
  year, each showing a per-year subtotal so the bars reconcile to the cards.

### 4.5 Distributors (manufacturer → distributor → retailer)
- Manufacturers can record which **distributor** each retailer is supplied by, to
  see who is connected to whom and which distributor is driving sales.
- Distributors are **tracking/attribution only** — no login, no wallet, **no
  points of their own**. Created manually in the panel or auto-created when
  importing retailers (a `distributor` column in the CSV).
- Each scan records the retailer's distributor **at scan time** (history is not
  rewritten if a retailer is later reassigned). The dashboard rolls up each
  distributor's connected retailers and their scans/points.

### 4.6 Retailer wallet
- Balance = sum of all ledger entries. History shows scans, redemptions,
  adjustments, and transfers between retailers.

### 4.7 Confirmations on points changes
- Every action that changes a points balance — redeem/claim a gift, transfer,
  manual adjust (+/-), and approve/reject a redemption — shows a **confirmation
  dialog** summarizing the effect before it commits. Scanning to earn is exempt
  (high-frequency; the result screen already shows the outcome).

### 4.8 Data export
- Every data tab in the panel — Customers, Distributors, Products, Reward shop,
  Claims, Redemptions — has an **Export CSV** action that downloads the current
  data as a spreadsheet. Claims exports respect the active filters; Redemptions
  exports all statuses (pending/approved/rejected) in one file.

### 4.9 Retailer experience
- The retailer webview has a persistent **navigation menu** (Home, Scan, Reward
  shop, Claims history, Log out) on every page.
- A successful scan shows a **celebratory animation** (the points count up with a
  confetti burst) so the retailer clearly sees they earned points. After a scan,
  **"Scan another" reopens the camera immediately** — no extra tap.

## 5. Key user flows

1. **Onboard manufacturer** — super admin creates account → manufacturer logs in.
2. **Set up rewards** — manufacturer sets points on their Vastra-sourced
   products, adds schemes, gifts, retailers, and distributors (retailer logins
   auto-created; city + distributor optional). Distributors and Customers also
   support **bulk CSV import** (the retailer CSV auto-creates + links
   distributors, and carries opening point balances over). Products and gifts
   import the same way; each imported list also has a **Delete all** so a bad
   import can be undone in one step.
3. **Generate & print** — in the Products tab, **Generate QR** opens an in-panel
   modal: pick a catalog product → set/confirm points → quantity →
   generate → save → print A4 PDF of QR labels (rendered in the browser).
4. **Earn** — retailer logs into YourApp → scans QR (or types manual code) →
   points awarded with scheme bonus (shown with a count-up + confetti animation);
   location captured. "Scan another" reopens the camera right away.
5. **Redeem** — retailer opens rewards shop → claims a gift → manufacturer
   approves → proof reference issued.
6. **Track** — manufacturer reviews dashboard map, region/product analytics, and
   claims.

## 6. Success metrics
- # active retailers scanning per manufacturer per month.
- Scan volume and points issued; redemption rate.
- Map coverage (share of scans with a captured location).
- Onboarding friction: retailers scanning successfully on first attempt.

## 7. Constraints & assumptions
- Phone camera + geolocation require **HTTPS** (production is HTTPS on Render).
- Geolocation precision is **city-level** (offline lookup, no external geocoder).
- A valid unredeemed code is a bearer token — security relies on the code being
  unguessable and single-use; physical control of the sticker is assumed.

## 8. Open items / future
- Rate limiting and hardening of scan/redeem against abuse (see security backlog).
- Native-app geolocation enablement if scan pages run inside an in-app WebView.
- Richer analytics (time series, retailer cohorts).

# Product Requirements Document — Vastra Loyalty Program

**Status:** Live in production · **Last updated:** 2026-06-18 · **Owner:** Vastra team

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

### 4.2 Catalog & rewards
- Manufacturers define **products** with base loyalty points.
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

### 4.4 Location & analytics
- A retailer's **city is optional** at registration; if omitted, it is detected
  from their **first scan's GPS** (nearest known city).
- The retailer's **shop location** pins to exact GPS on the first scan that shares
  location, and is then locked.
- **Each scan records its own GPS** (captured once per session, reused that
  session), so the dashboard map shows where scans actually happen over time.
- Dashboard shows totals, scans by region/product, top retailers, and an
  interactive India map of scan locations.

### 4.5 Retailer wallet
- Balance = sum of all ledger entries. History shows scans, redemptions,
  adjustments, and transfers between retailers.

## 5. Key user flows

1. **Onboard manufacturer** — super admin creates account → manufacturer logs in.
2. **Set up rewards** — manufacturer adds products, schemes, gifts; adds retailers
   (login auto-created; city optional).
3. **Generate & print** — pick product → quantity → generate → save → print A4 PDF
   of QR labels.
4. **Earn** — retailer logs into YourApp → scans QR (or types manual code) →
   points awarded with scheme bonus; location captured.
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

# System Architecture

> Audience: Vastra backend + mobile integrators. See the [status legend](README.md).

## 1. Overview

The Loyalty QR backend is a single **FastAPI** service (Python 3.12+) backed by
**PostgreSQL** in production (SQLite for local dev). It powers a
manufacturer→retailer loyalty program: manufacturers generate QR codes that are
printed on product/box stickers; retailers scan them to earn points and redeem
gifts.

It serves three surfaces from one container:

- **REST API** (`/…`, docs at `/docs`) — the source of truth for all loyalty data.
- **React admin panel** (`/panel`) — manufacturer + super-admin web UI.
- **Plain-HTML webviews** (`/web/*`) — the current mobile UI; being replaced by
  native Vastra/YourApp screens that call the REST API directly.

The loyalty backend is a pure request/response service: **no background jobs, no
cron, no workers, no message queue.** Schema migrations run synchronously on boot.

## 2. System components

```mermaid
flowchart TB
  subgraph Vastra["Vastra Platform (manufacturer side)"]
    VApp["Vastra App (native)"]
    VBack["Vastra Backend\n(System of Record: Products,\nManufacturer identity)"]
  end
  subgraph YourApp["YourApp (per-manufacturer, retailer side)"]
    RApp["YourApp (native)"]
    RBack["YourApp Backend\n(Retailer identity provider)"]
  end
  subgraph Loyalty["Loyalty Backend (this service)"]
    API["FastAPI REST API"]
    DB[("PostgreSQL / Neon\n(loyalty domain + ledger)")]
    Panel["React Admin Panel /panel"]
    Web["Webviews /web/*"]
    API --> DB
    Panel --> API
    Web --> API
  end

  VApp --> VBack
  RApp --> RBack
  VBack -->|"SSO assertion + QR generation"| API
  RApp -->|"SSO assertion, scan, wallet, claims"| API
  RBack -->|"mints retailer SSO assertion"| RApp
  VBack -->|"mints manufacturer SSO assertion"| VApp
```

## 3. Responsibility of each system

| System | Responsibility |
|---|---|
| **Vastra Backend** | System of Record for **products** and **manufacturer identity**. Authenticates manufacturers, mints SSO assertions, and (target architecture) originates QR generation with trusted product data. |
| **YourApp Backend** | Identity provider for **retailers**. Authenticates retailers and mints retailer SSO assertions. |
| **Loyalty Backend** | System of Record for the **loyalty domain**: QR batches/codes, the points ledger & wallets, schemes, gifts, claims, and analytics. Validates and redeems QR codes; enforces multi-tenancy. |
| **Loyalty Admin Panel** | Web client of the Loyalty API for manufacturers + super admin. |
| **Native apps (Vastra App / YourApp)** | Presentation clients. Exchange a parent assertion for a loyalty token, then call loyalty APIs. |

## 4. Domain ownership

SoR = System of Record (owns lifecycle + truth). "Ref" = referenced by external
id. "Snapshot" = point-in-time copy stored in loyalty so history never changes.

| Entity | SoR | Read by | Written by | In Loyalty |
|---|---|---|---|---|
| **Manufacturers** | Vastra | Vastra, Loyalty, Panel | Vastra (provision); Loyalty (panel password, tokens) | Ref via `external_id`; `display_name` local copy |
| **Retailers** | Split: identity = YourApp/Vastra; loyalty profile = Loyalty | all | Upstream (identity); Loyalty (region, location, distributor) | Ref via `external_id` |
| **Products** | **Vastra** | Vastra, Loyalty (snapshot), Panel | **Vastra only** (loyalty CRUD transitional) | ✅ Ref via `product_external_id` + **snapshot** (see [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md)) |
| **QR Batches** | Loyalty | Loyalty, Panel, Vastra App | Loyalty (triggered by Vastra) | Owned; embeds product snapshot |
| **QR Codes** | Loyalty | Loyalty, scanners | Loyalty (generate; redeem) | Owned outright |
| **Schemes** | Loyalty | Loyalty, Panel | Loyalty (manufacturer) | Owned; references products by id |
| **Wallets** | Loyalty | Loyalty, clients | Loyalty (via ledger only) | Owned (derived = `SUM(ledger)`) |
| **Claims** | Loyalty | Loyalty, Panel, retailer | Loyalty (claim / approve / reject) | Owned |
| **Gifts** | Loyalty | Loyalty, Panel, retailer | Loyalty (manufacturer) | Owned |
| **Analytics** | Loyalty (derived) | Panel, Vastra | nobody (computed) | Owned / derived |
| **Points Ledger** | Loyalty | Loyalty, Panel | Loyalty (append-only) | Owned; holds snapshots (region, distributor, product) |

**Principle:** identity is owned upstream (referenced by `external_id`); loyalty
*value* (points, codes, claims) is owned by loyalty. Reference the living,
snapshot the historical.

## 5. Manufacturer flow (high level)

```mermaid
sequenceDiagram
  actor M as Manufacturer
  participant VA as Vastra App
  participant VB as Vastra Backend
  participant L as Loyalty API
  M->>VA: Open loyalty section
  VA->>VB: Request SSO assertion
  VB-->>VA: Signed manufacturer JWT (HS256)
  VA->>L: POST /auth/sso/manufacturer {assertion}
  L-->>VA: loyalty token
  M->>VA: Select product, request N QR codes
  VA->>VB: Generate request (product chosen in Vastra catalog)
  VB->>L: POST /qr/generate (product_external_id + snapshot)
  L-->>VB: batch + codes
  VB-->>VA: batch result
  VA->>L: GET /qr/batches/{id}/print (PDF)
  M->>VA: View analytics / claims
  VA->>L: GET /analytics/dashboard, /claims, /gift-claims
```

## 6. Retailer flow (high level)

```mermaid
sequenceDiagram
  actor R as Retailer
  participant RA as YourApp
  participant RB as YourApp Backend
  participant L as Loyalty API
  R->>RA: Open app (already logged in)
  RA->>RB: Request SSO assertion
  RB-->>RA: Signed retailer JWT (HS256)
  RA->>L: POST /auth/sso/retailer {assertion}
  L-->>RA: loyalty retailer token
  R->>RA: Scan a QR sticker
  RA->>L: POST /scan {code, lat?, lng?}
  L-->>RA: points awarded + new balance
  R->>RA: View wallet / rewards / claims
  RA->>L: GET /retailer/wallet, /retailer/shop, /retailer/claims
  R->>RA: Redeem a gift
  RA->>L: POST /retailer/claim {gift_id}
```

## 7. Trust boundaries

```mermaid
flowchart LR
  subgraph Untrusted["Untrusted (client devices)"]
    VA["Vastra App"]
    RA["YourApp"]
  end
  subgraph Trusted["Trusted (server-side)"]
    VB["Vastra Backend"]
    RB["YourApp Backend"]
    L["Loyalty API"]
  end
  VA -. "holds loyalty token only" .-> L
  RA -. "holds loyalty token only" .-> L
  VB == "shared SSO_SECRET (HMAC)\n+ trusted product data" ==> L
  RB == "shared SSO_SECRET (HMAC)" ==> RA
```

Key boundary rules:
- **The shared `SSO_SECRET` lives only on backends**, never in a mobile app.
- **Mobile devices are untrusted**: they never assert their own identity to
  loyalty (it comes from the signed token) and never supply economically
  sensitive data such as a QR's points value.
- **Retailer identity at scan time comes only from the loyalty token**, never
  from the request body — points can only be credited to the authenticated
  retailer.
- **Cross-tenant isolation:** every owned row carries `manufacturer_id`; a
  retailer belongs to exactly one manufacturer; cross-manufacturer scans/claims
  are rejected.

## 8. Data ownership principles

1. **Single SoR per entity** — no system writes another system's source of truth.
2. **Reference for the living, snapshot for the historical** — current upstream
   records are referenced by `external_id`; values that must stay correct forever
   (points on a printed sticker, product name on a past scan) are snapshotted.
3. **Append-only ledger** — all balance changes are ledger rows; the wallet is
   `SUM(points_ledger)`, never a mutable field. See [QR_WORKFLOW](QR_WORKFLOW.md).
4. **No second catalog** — loyalty stores product *references and snapshots*, not
   a product catalog. See [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md).

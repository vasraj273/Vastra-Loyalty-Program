# Integration Checklist

> Practical, role-separated checklist for taking the Vastra ↔ Loyalty integration
> to production. Cross-refs: [SSO_INTEGRATION](SSO_INTEGRATION.md),
> [API_REFERENCE](API_REFERENCE.md), [DEPLOYMENT_GUIDE](DEPLOYMENT_GUIDE.md),
> [ERROR_REFERENCE](ERROR_REFERENCE.md), [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md).

Legend: ✅ works today · 🟡 loyalty backend implemented, pending Vastra's real
product-list API contract (see [PRODUCT_INTEGRATION §8](PRODUCT_INTEGRATION.md#8-open-items)).

---

## Backend Team (Vastra / YourApp backends)

**Configure SSO** ✅
- [ ] Obtain and securely store `SSO_SECRET` (server-side only; never in apps).
- [ ] Mint HS256 assertions with exact claims (`iss`, `aud=loyalty`, `role`,
      `sub`=external_id, `iat`, short `exp`; retailer adds `manufacturer_external_id`).
- [ ] Keep assertion `exp` ≤ `SSO_MAX_AGE` (120 s); sync server clocks (NTP).
- [ ] Implement "mint a fresh assertion on demand" (apps re-exchange on `401`).

**Import manufacturers** ✅
- [ ] Create each manufacturer in loyalty **with `external_id`** (the Vastra
      product/manufacturer id space).
- [ ] Give each a panel password (web panel login is separate from SSO).
- [ ] Verify `POST /auth/sso/manufacturer` returns a token for a known `external_id`.

**Import retailers** ✅
- [ ] Provision retailers per manufacturer **with `external_id`** via
      `POST /retailers` or `POST /retailers/import` (CSV `external_id` column).
- [ ] Confirm `external_id` is unique per manufacturer.
- [ ] Verify `POST /auth/sso/retailer` (with `manufacturer_external_id`) returns a token.

**Configure secrets**
- [ ] `SSO_SECRET` distributed only to Vastra + YourApp backends + loyalty env.
- [ ] No secret committed to source control or shipped in app bundles.

**Verify APIs**
- [ ] Run the smoke checklist in [DEPLOYMENT_GUIDE §8](DEPLOYMENT_GUIDE.md#8-verification-checklist-post-deploy-smoke).
- [ ] Confirm provisioning gate: unknown `external_id` → `403`, **no row created**.

**Serve the product-list API** 🟡
- [ ] Expose a product-list endpoint the Loyalty Backend can call server-side
      (`GET /vastra/products` proxies it via `app/vastra_client.py`); share
      URL + auth mechanism (`VASTRA_API_BASE_URL` / `VASTRA_API_KEY`).
- [ ] Confirm response fields (product id, name, sku) and whether the list is
      scoped per-manufacturer server-side or needs a query param.
- [ ] QR generation itself is now **panel-driven** (manufacturer logs into the
      loyalty admin panel directly) — no server-to-server `/qr/generate` call
      from the Vastra backend is needed. See [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md).

---

## Mobile Team (Android & iOS)

**Implement authentication** ✅
- [ ] Fetch assertion from parent backend → `POST /auth/sso/{manufacturer|retailer}`.
- [ ] Store loyalty token in Keychain / Keystore; send `Authorization: Bearer`.
- [ ] On `401`: re-exchange a fresh assertion → retry once → else route to login.
      (Single active session: logging in again elsewhere invalidates this token —
      a `401` can simply mean the user signed in on another device.)
- [ ] On `403 Account is blocked`: stop retrying, show an "account disabled" state
      (emergency lockout cleared only by an admin in the DB).
- [ ] Logout calls `/auth/logout` or `/auth/retailer/logout`, then clears the token.

**QR generation is not a mobile-app feature** ✅
- [ ] Nothing to implement here — the manufacturer generates QR codes from
      the **loyalty admin panel** (web), not the Vastra App. If the app needs
      a "Generate QR" entry point, deep-link/redirect to the panel rather than
      calling loyalty's `/qr/generate` or product endpoints directly.

**Implement scanning (retailer app)** ✅
- [ ] Camera scanner + manual 6-char fallback field.
- [ ] Request location up front (high-accuracy GPS); proceed even if denied.
- [ ] `POST /scan {code, lat?, lng?}`; show points + new balance; handle box
      scans (`items_registered`).
- [ ] Handle `404 Invalid code` and `409 already redeemed` as normal UX states.
- [ ] **Do not blind-retry** `/scan` on ambiguous failure — verify via `/retailer/me`.

**Wallet** ✅
- [ ] `GET /retailer/wallet` → balance + history (note: latest 100, no pagination).

**Rewards & Claims** ✅
- [ ] `GET /retailer/shop` → gifts + `affordable`; **confirm** before `POST /retailer/claim`.
- [ ] Show returned `reference` + new balance; handle `409 Not enough points`.
- [ ] `GET /retailer/claims` for history; manufacturer app uses `GET /gift-claims`
      + approve/reject (with confirmation).

**Error handling** ✅
- [ ] Implement the status-code matrix in [ERROR_REFERENCE](ERROR_REFERENCE.md).
- [ ] Backoff + jitter on `429`/`5xx` for GETs; verify-first for write retries.
- [ ] Loading/empty/skeleton states per [MOBILE_INTEGRATION_GUIDE](MOBILE_INTEGRATION_GUIDE.md).

---

## DevOps

**Environment variables** ✅
- [ ] `DATABASE_URL` (Neon pooled), `QR_BASE_URL` (HTTPS origin + `/web/scan`).
- [ ] `SSO_SECRET` (+ optional `SSO_ISSUERS`/`SSO_AUDIENCE`/`SSO_MAX_AGE`).
- [ ] `VASTRA_API_BASE_URL` + `VASTRA_API_KEY` (+ optional `VASTRA_API_TIMEOUT`) —
      required for the panel's Products tab / QR generation to load a catalog.
- [ ] `RL_STORAGE_URI` if running more than one process/replica.

**Deployment** ✅
- [ ] Docker image builds panel + serves API/`/panel`/`/web/*`.
- [ ] HTTPS enforced; CORS restricted to real origins.
- [ ] Confirm boot runs `init_db`+`migrate`+`create_constraints` cleanly (idempotent).
- [ ] Never run `seed.py`/`reset_db()` against production.

**Monitoring**
- [ ] Liveness `GET /openapi.json`; readiness `GET /public/cities` (see
      [DEPLOYMENT_GUIDE §7](DEPLOYMENT_GUIDE.md#7-health-checks)).
- [ ] Alert on elevated `5xx`, `401/403` spikes (auth/provisioning issues), and
      `429` rates (limits too tight or abuse).
- [ ] Track `/scan` and `/qr/generate` latency/volume.

**Logging**
- [ ] Capture request id, status, route, latency. **Never log** the `SSO_SECRET`,
      bearer tokens, or `?token=` query values.
- [ ] Retain Neon backups / point-in-time restore window for rollback.

---

## QA

**Test cases — SSO** ✅
- [ ] Valid manufacturer assertion → 200 + working token.
- [ ] Valid retailer assertion (with `manufacturer_external_id`) → 200 + token.
- [ ] Unknown `external_id` → 403, **no row created**.
- [ ] Tampered signature / wrong secret → 401.
- [ ] Expired (`exp`) and stale (`iat` > max age) → 401.
- [ ] Wrong `aud`/`iss`/`role` (e.g. manufacturer assertion at retailer endpoint) → 401.
- [ ] Cross-tenant retailer (valid id under wrong `manufacturer_external_id`) → 403.

**Test cases — QR & scan** ✅
- [ ] Generate batch → codes returned; PDF downloads; PNG renders.
- [ ] Scan valid code → correct base+bonus points + new balance.
- [ ] Re-scan same code → 409. Box scan → all children credited once.
- [ ] Concurrent scans of one code credit it **exactly once** (double-spend test).
- [ ] Cross-manufacturer code → 404 (identical to unknown code).

**Test cases — wallet/rewards/claims** ✅
- [ ] Claim a gift → points debited + reference; reject → points refunded.
- [ ] Claim with insufficient points → 409.
- [ ] Wallet balance always equals sum of ledger effects.

**Security checks**
- [ ] No `SSO_SECRET`/token leakage in logs, crash reports, or app bundles.
- [ ] Tokens stored only in secure storage on device.
- [ ] HTTPS enforced; `?token=` not used for normal app traffic.
- [ ] Tenancy: a manufacturer cannot read/generate for another's data; a retailer
      cannot credit another shop.
- [ ] Rate limits enforced (and shared across replicas if applicable).

**Integration validation**
- [ ] End-to-end: login to panel → GET /vastra/products → generate → print →
      scan (via SSO) → wallet → claim → approve, across two manufacturers to
      prove isolation.
- [ ] Clock-skew resilience for assertions.
- [ ] Rollback drill: redeploy previous image; confirm additive schema is
      backward-compatible.

---

## 🟡 Gate before the Vastra product-list API is live

The loyalty side is fully built (`app/vastra_client.py`, `GET
/vastra/products`, `product_points`, panel Products tab/Generate QR modal).
What's still needed from Vastra: their real product-list API contract (URL,
auth mechanism, response field names, per-manufacturer scoping) — see the
open items in
[PRODUCT_INTEGRATION §8](PRODUCT_INTEGRATION.md#8-open-items). Until
`VASTRA_API_BASE_URL`/`VASTRA_API_KEY` point at a real endpoint, `GET
/vastra/products` fails closed with `502` and the panel's Products tab /
Generate QR flow can't load a catalog.

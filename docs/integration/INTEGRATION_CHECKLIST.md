# Integration Checklist

> Practical, role-separated checklist for taking the Vastra ↔ Loyalty integration
> to production. Cross-refs: [SSO_INTEGRATION](SSO_INTEGRATION.md),
> [API_REFERENCE](API_REFERENCE.md), [DEPLOYMENT_GUIDE](DEPLOYMENT_GUIDE.md),
> [ERROR_REFERENCE](ERROR_REFERENCE.md), [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md).

Legend: ✅ works today · 🟡 loyalty backend implemented (Phase 1); depends on the
broader product-ownership rollout — Vastra-originated `/qr/generate` calls,
product CRUD removal, and the `scheme_products` → `product_external_id` migration.

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

**QR generation origination** 🟡
- [ ] Decide/confirm server-to-server origination (Vastra Backend → Loyalty) and
      auth (reuse SSO exchange recommended). See [PRODUCT_INTEGRATION](PRODUCT_INTEGRATION.md).
- [ ] Resolve trusted product snapshot (name, sku, **points policy**) before calling.

---

## Mobile Team (Android & iOS)

**Implement authentication** ✅
- [ ] Fetch assertion from parent backend → `POST /auth/sso/{manufacturer|retailer}`.
- [ ] Store loyalty token in Keychain / Keystore; send `Authorization: Bearer`.
- [ ] On `401`: re-exchange a fresh assertion → retry once → else route to login.
- [ ] Logout calls `/auth/logout` or `/auth/retailer/logout`, then clears the token.

**Implement QR generation (manufacturer app)** 🟡
- [ ] Select product **in the Vastra catalog** (never fetch products from loyalty).
- [ ] Request generation **via the Vastra backend** (don't send points from the app).
- [ ] Render/print: `GET /qr/batches/{id}/print` (PDF) or per-code PNG
      `GET /qr/codes/{token}/image`. Offer "Save batch".

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
- [ ] End-to-end: SSO → generate (via Vastra backend) → print → scan → wallet →
      claim → approve, across two manufacturers to prove isolation.
- [ ] Clock-skew resilience for assertions.
- [ ] Rollback drill: redeploy previous image; confirm additive schema is
      backward-compatible.

---

## 🟡 Gate before product-ownership go-live

Confirm the four open decisions in
[PRODUCT_INTEGRATION §8](PRODUCT_INTEGRATION.md#8-open-items-to-confirm-before-implementation)
and complete the migration in [PRODUCT_INTEGRATION §7](PRODUCT_INTEGRATION.md#7-migration-plan-additive-neon-safe-no-reseeddrop)
before switching QR generation to the `product_external_id` contract.

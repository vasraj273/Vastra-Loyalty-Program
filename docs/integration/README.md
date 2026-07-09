# Loyalty Backend — Integration Documentation Package

This folder is the **handoff package** for the Vastra backend and mobile teams
integrating with the Loyalty QR backend. It is written so an external team can
integrate **without reading the source code**.

> **Status legend used throughout these docs**
> - ✅ **Implemented** — live in the current backend, callable today.
> - 🟡 **Agreed / Planned** — an approved architecture decision **not yet
>   implemented in code**. Clearly flagged wherever it appears so you never
>   build against something that isn't shipped.

## Documents

| # | Document | What it covers |
|---|---|---|
| 1 | [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | Components, responsibilities, domain ownership, trust boundaries, flows |
| 2 | [SSO_INTEGRATION.md](SSO_INTEGRATION.md) | SSO architecture, JWT assertion format, token exchange, env vars, sequences ✅ |
| 3 | [MOBILE_INTEGRATION_GUIDE.md](MOBILE_INTEGRATION_GUIDE.md) | Manufacturer + retailer app flows, APIs, UX, errors, retries |
| 4 | [API_REFERENCE.md](API_REFERENCE.md) | Endpoint-by-endpoint contract (SSO + QR + scan + wallet + claims) |
| 5 | [QR_WORKFLOW.md](QR_WORKFLOW.md) | Generation → batch → scan → redemption → ledger → claims → analytics |
| 6 | [PRODUCT_INTEGRATION.md](PRODUCT_INTEGRATION.md) | Vastra as product System of Record, pulled server-side; panel-driven QR generation ✅ (CRUD removed; `scheme_products` migration pending) |
| 7 | [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | Env vars, migrations, SSO config, health, rollback, prod checklist |
| 8 | [ERROR_REFERENCE.md](ERROR_REFERENCE.md) | Every API error, meaning, client behavior, retry guidance |
| 9 | [INTEGRATION_CHECKLIST.md](INTEGRATION_CHECKLIST.md) | Practical checklists: Backend / Mobile / DevOps / QA |

## Reading order

1. **SYSTEM_ARCHITECTURE** for the mental model.
2. **SSO_INTEGRATION** — nothing else works until auth does.
3. **API_REFERENCE** + **ERROR_REFERENCE** as you build.
4. **QR_WORKFLOW** and **MOBILE_INTEGRATION_GUIDE** for the feature flows.
5. **PRODUCT_INTEGRATION** for the product-ownership model — pull-based, panel-driven
   (implemented; `scheme_products` migration to `product_external_id` still pending).
6. **DEPLOYMENT_GUIDE** + **INTEGRATION_CHECKLIST** for go-live.

## Companion (existing repo docs)

- `../PROJECT_CONTEXT.md` — full project orientation.
- `../TRD.md` — technical design. `../PRD.md` — product requirements.
- `../../CLAUDE.md` — contributor conventions. `../../DEPLOY.md` — base deploy notes.

**Base URL:** all routes are relative to the deployed origin (e.g.
`https://loyalty.<host>`). Interactive OpenAPI is at `/docs`, schema at
`/openapi.json`.

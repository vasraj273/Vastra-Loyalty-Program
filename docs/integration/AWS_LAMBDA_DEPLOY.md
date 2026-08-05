# AWS Lambda + RDS deployment

> The production target: **backend on Lambda, database on RDS for MySQL**.
> Base deploy notes: [`../../DEPLOY.md`](../../DEPLOY.md). Database provisioning:
> [`MYSQL_SETUP.md`](MYSQL_SETUP.md). Env var reference:
> [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) §2.

This app was written as a long-lived container (one FastAPI process serving the
API, the built panel at `/panel`, and the webviews at `/web/*`). Lambda runs it
fine, but five of its assumptions stop holding — a persistent process, outbound
internet, unbounded request time, a stable connection pool, and in-process
memory. Each section below is one of those, with the setting that fixes it.

**Read §4 before launch day.** It is the one that silently breaks manufacturer
login.

---

## 1. Make the image Lambda-invocable

FastAPI speaks ASGI; Lambda invokes a handler. The repo `Dockerfile` ends in
`uvicorn`, which Lambda cannot call directly.

Use the **AWS Lambda Web Adapter**, which keeps the image exactly as it is —
the adapter runs as a Lambda extension, receives the invocation, and proxies it
to uvicorn on `PORT` over normal HTTP. No application code changes, so the same
image still runs locally, on ECS, or anywhere else.

**This is already applied** in the repo `Dockerfile`:

```dockerfile
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 \
     /lambda-adapter /opt/extensions/lambda-adapter
ENV AWS_LWA_INVOKE_MODE=response_stream
```

`ENV PORT=8000` and the `uvicorn` `CMD` were already there and are unchanged —
the adapter proxies to that port. The image therefore still runs identically
under plain `docker run`, on Render, or on ECS; the adapter only activates
inside the Lambda runtime.

> Confirm the adapter tag against the [current
> release](https://github.com/awslabs/aws-lambda-web-adapter) — `0.9.1` is
> pinned deliberately rather than floating on `:latest`, so a redeploy can't
> pick up a different adapter without a commit.

Then publish the image to ECR and create the function from it (**package type:
Image**). The alternative, Mangum, requires a code change (`handler =
Mangum(app)`) and gives up local `uvicorn` parity; the adapter is preferred here
for that reason.

## 2. Use a Function URL, not API Gateway

**API Gateway caps a request at 29 seconds, and the CSV import will exceed it.**

Retailer import hashes a PBKDF2 password per new retailer at 20,000 iterations
([`main.py` `import_retailers_csv`](../../app/main.py)). Measured on a 6-core
machine: **250 hashes = 2.0s wall ≈ 12 core-seconds**. The panel sends the CSV
in 250-row chunks, so *one chunk* spends ~12s on hashing alone at 1 vCPU, before
250 INSERTs and per-city geocoding. A 2,000-row customer list is 8 such chunks.

A **Lambda Function URL** inherits the function timeout (up to 15 minutes)
instead. Configure:

- **Auth type: `NONE`.** The app does its own bearer-token auth on every
  endpoint. `AWS_IAM` would additionally require every caller to SigV4-sign —
  which the mobile webviews and the panel cannot do, and which would break the
  print-PDF link specifically: it authenticates via `?token=` precisely so it
  can be opened in a new browser tab.
- **Invoke mode:** `RESPONSE_STREAM` — see §3.
- **Function timeout:** 300s is comfortable; imports are the long pole.

If a CloudFront distribution or custom domain sits in front, make sure its own
origin timeout is raised to match — CloudFront defaults to 30s and would
reintroduce exactly the cap you just removed.

## 3. Response size: print PDFs can exceed the buffered cap

Lambda's **buffered** response limit is **6 MB**; `RESPONSE_STREAM` raises it to
**20 MB**. The print-PDF endpoint returns a whole sticker sheet in one response,
and it grows linearly with the batch:

Measured with `app/pdf_service.build_pdf` (~5.2 KB per sticker):

| Codes in one PDF | Size | Buffered (6 MB) | Streamed (20 MB) |
|---|---|---|---|
| 100 | 0.52 MB | ok | ok |
| 500 | 2.58 MB | ok | ok |
| 1,000 | 5.16 MB | ok | ok |
| 2,000 | 10.32 MB | **over** | ok |

So the ceiling is roughly **1,150 codes buffered, 3,800 streamed**. A single
batch of 2,000 stickers — an entirely ordinary print run — already breaks the
buffered limit. `AWS_LWA_INVOKE_MODE=response_stream` (§1) plus a
`RESPONSE_STREAM` Function URL (§2) is therefore required, not optional.

Past ~3,800 codes, split the run into several batches. That is the sane print
workflow regardless of runtime, and generation already works in batches.

## 4. Networking — the one that breaks manufacturer login

RDS lives in a VPC. To reach it, the Lambda must be attached to that VPC. **A
Lambda in a VPC has no route to the internet** unless you give it one.

This app makes two outbound calls:

| Call | Where | Breaks if no egress |
|---|---|---|
| Vastra OTP login | [`app/vastra_client.py`](../../app/vastra_client.py) | **Manufacturers cannot log in.** The call hangs until `VASTRA_API_TIMEOUT` (10s), then returns `502 "Vastra login service unavailable"`. |
| Reverse geocoding | [`app/geo.py`](../../app/geo.py) → `nominatim.openstreetmap.org` | Shop addresses stop resolving. Best-effort by design, so scans still succeed — but every scan pays the timeout first. |

Pick one:

- **NAT Gateway** in a public subnet, with the Lambda's private subnets routing
  `0.0.0.0/0` to it. Correct and boring; ~$32/month plus data processing.
- **VPC endpoints** do *not* help here — they cover AWS services, and both calls
  above are to third-party hosts on the public internet.
- **Skip the VPC**: make RDS publicly accessible, restrict its security group to
  the Lambda's egress, and keep `?ssl=true` in `DATABASE_URL`. No NAT cost, and
  traffic is still TLS-encrypted, but the database is exposed to the internet at
  the network layer. Acceptable only with a tight security group.

**Verify egress before launch**, because the failure looks like a Vastra problem
rather than a networking one. From the deployed function, a request to
`VASTRA_API_BASE_URL` must return something other than a timeout.

## 5. Database connections — use RDS Proxy

`get_db()` opens a **new PyMySQL connection per request**
([`app/database.py`](../../app/database.py)), then issues two `SET SESSION`
statements (`READ COMMITTED` and `time_zone = '+00:00'` — both load-bearing, see
[`../../CLAUDE.md`](../../CLAUDE.md)). That is cheap against a local socket and
expensive against RDS: every request pays a TCP + TLS handshake and two extra
round trips.

Worse, Lambda concurrency maps 1:1 onto connections. 100 concurrent invocations
= 100 connections; a `db.t3.micro` allows about 60, and `db.t3.small` about 150.
A scan burst therefore fails with "too many connections" rather than degrading.

- Put **RDS Proxy** between Lambda and RDS and point `DATABASE_URL` at the proxy
  endpoint. It pools and reuses backend connections across invocations.
- Set **reserved concurrency** on the function as a hard ceiling that stays
  under the instance's `max_connections`.
- Keep `?ssl=true` in the URL — RDS Proxy requires TLS.

## 6. Schema DDL runs on every cold start

The app's `lifespan` runs `init_db()` + `migrate()` + `create_constraints()`
before serving ([`app/main.py`](../../app/main.py)). In a container that happens
once at boot. On Lambda it happens **on every cold start**, which means:

- Every cold start pays the full `information_schema` migration check.
- Several cold starts firing at once run `ADD CONSTRAINT` concurrently against
  the same tables, which MySQL can answer with a lock wait or a deadlock.

The DDL is idempotent and additive, so this is a latency and lock-contention
problem, not a correctness one. Recommended handling:

1. Apply the schema **once, out of band**, before pointing traffic at the
   function — run `python bootstrap_admin.py …` (§7) from a machine with
   `DATABASE_URL` set. It calls the same `init_db/migrate/create_constraints`.
2. Keep **provisioned concurrency ≥ 1** so the steady state has no cold start.
3. If cold-start latency still hurts, gate the boot DDL behind an env var so
   normal invocations skip it entirely. That is a small code change to
   `lifespan` and is not implemented today — ask before assuming it exists.

## 7. There are no accounts on a fresh database

Startup creates and migrates tables but **never seeds**. A newly provisioned RDS
therefore has zero accounts and nobody can log into `/panel`.

Two ways in, and the first needs nothing:

- **Vastra OTP login auto-provisions the manufacturer.** `POST
  /auth/vastra/verify-otp` matches on `external_id` (Vastra's
  `organization_Id`) and **inserts a new manufacturer** when there is no match,
  refreshing `display_name` from the org name. So the first successful OTP login
  creates the account. This is deliberately unlike SSO
  ([`SSO_INTEGRATION.md`](SSO_INTEGRATION.md)), which refuses to auto-create.
  It requires `VASTRA_API_BASE_URL` **and** working egress (§4).
- **`bootstrap_admin.py`** creates a super admin (and optionally a
  password-login manufacturer) **non-destructively**. Idempotent — an existing
  username is left untouched and no password is ever reset.

  ```bash
  export DATABASE_URL='mysql://user:pass@proxy-endpoint:3306/db?ssl=true'
  python bootstrap_admin.py --admin-user admin        # prompts for the password
  ```

> **Never run `seed.py` against the production database.** It drops every table.
> It requires `ALLOW_MYSQL=1` precisely so it cannot be run against MySQL by
> accident.

## 8. Rate limiting needs a shared store

Limits default to **in-process memory**
([`app/main.py`](../../app/main.py)). Every Lambda execution environment has its
own, so with N warm environments the effective limit is N× the configured one,
and it resets on every cold start — i.e. login throttling is close to
meaningless.

Set `RL_STORAGE_URI` to an **ElastiCache Redis** endpoint (reachable from the
Lambda's subnets) to make `RL_LOGIN` and friends real. If you accept the
weakened guarantee for launch, set it consciously rather than by omission.

Note `RL_SCAN` is keyed by **IP** for the `/yourapp/*` endpoints, so YourApp's
entire backend shares one bucket — raise it if their scan volume is bulk.

## 9. Environment variables

Set every one of these in the **function's own configuration**. This app has no
dotenv loader and `.env` is gitignored, so anything missing fails closed in
production while working perfectly on your machine.

| Variable | Value | If unset |
|---|---|---|
| `DATABASE_URL` | `mysql://user:pass@<rds-proxy>:3306/db?ssl=true` | Falls back to SQLite in the function's ephemeral filesystem — **every invocation may see a different empty database** |
| `QR_BASE_URL` | `https://<host>/web/scan` | Every generated QR encodes `127.0.0.1`. **Irreversible once stickers are printed** |
| `VASTRA_API_BASE_URL` | Vastra's production origin | Manufacturer OTP login returns `502` |
| `VASTRA_API_KEY` | as issued by Vastra | — |
| `YOURAPP_API_KEY` | long random string | `/yourapp/qr/lookup` + `/yourapp/scan` return `503` |
| `SSO_SECRET` | long random string | `/auth/sso/*` return `503` |
| `RL_STORAGE_URI` | `redis://<elasticache>:6379` | Rate limits are per-execution-environment (§8) |
| `USE_SAMPLE_PRODUCTS` | leave unset | (unset is correct — the Products tab prompts for a CSV import) |
| `PORT` | `8000` | Adapter cannot reach uvicorn |
| `AWS_LWA_INVOKE_MODE` | `response_stream` | Print PDFs over 6 MB fail (§3) |

Store `VASTRA_API_KEY`, `YOURAPP_API_KEY`, `SSO_SECRET` and the database
password in **Secrets Manager** or SSM Parameter Store rather than as plaintext
function config.

## 10. Sizing

Lambda allocates CPU proportionally to memory; **1,769 MB ≈ 1 full vCPU**.
Because the import path is CPU-bound on PBKDF2 (§2), memory is really a CPU
setting here:

| Memory | ~vCPU | 250-row import chunk (hashing only) |
|---|---|---|
| 512 MB | ~0.3 | ~40s |
| 1,024 MB | ~0.6 | ~20s |
| **1,769 MB** | **1.0** | **~12s** |
| 3,008 MB | ~1.8 | ~7s |

**Use 1,769 MB or more.** Below that, large imports get slow enough to hit even
the Function URL's ceiling once inserts and geocoding are added. A faster
function is also often *cheaper*, since Lambda bills memory × duration.

If imports remain uncomfortable, lower the panel's chunk size from 250 (in
[`panel/src/tabs/Customers.jsx`](../../panel/src/tabs/Customers.jsx),
`splitCsvChunks(csv, 250)`) — more requests, each well clear of any timeout.

## 11. Launch checklist

- [ ] Image built with the adapter lines (§1), pushed to ECR, function created as **package type: Image**
- [ ] Function URL created, **invoke mode `RESPONSE_STREAM`**, timeout ≥ 300s (§2, §3)
- [ ] Memory **≥ 1,769 MB** (§10)
- [ ] Egress verified — a live call to `VASTRA_API_BASE_URL` does not time out (§4)
- [ ] RDS Proxy in front of RDS, `DATABASE_URL` points at the proxy, reserved concurrency set (§5)
- [ ] Schema applied out of band; provisioned concurrency ≥ 1 (§6)
- [ ] `QR_BASE_URL` set to the real HTTPS origin **before any print run** (§9)
- [ ] An account exists — Vastra OTP login, or `bootstrap_admin.py` (§7)
- [ ] `RL_STORAGE_URI` set, or the weaker guarantee consciously accepted (§8)
- [ ] Secrets in Secrets Manager, not plaintext function config (§9)
- [ ] Smoke test: `/docs` loads · `/panel/` loads · OTP login succeeds · generate 5 codes · scan one · print PDF opens

## 12. What this runtime does not change

Worth stating, because these are the parts people expect to break and don't:

- **The panel and webviews are served by the same function.** `/panel` and
  `/web/*` are static files inside the image, so no S3/CloudFront origin split
  is required (though CloudFront in front is a reasonable optimisation).
- **The app is stateless.** All state is in MySQL; nothing is held between
  requests except the rate-limit counters discussed in §8.
- **Sessions survive fine.** Auth tokens are database rows, not in-memory
  sessions, so any invocation can serve any user.
- **Schema evolution is unchanged** — additive and idempotent, applied by
  `migrate()`. Never reseed or drop to apply a schema change.

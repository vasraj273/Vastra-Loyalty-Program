# MySQL setup (AWS RDS) — handoff

Everything the database owner needs to provision MySQL for the loyalty backend.
The application creates and migrates its own schema on boot, so there is no SQL
file to run by hand — but the server must be configured as described below or
startup DDL will fail.

Local development still uses SQLite with zero setup (leave `DATABASE_URL`
unset). MySQL is only for deployed environments.

---

## 1. Server requirements

| Requirement | Value | Why |
|---|---|---|
| Engine | **MySQL 8.0.13 or newer** | `created_at` columns use expression defaults (`DEFAULT (CAST(UTC_TIMESTAMP() AS CHAR))`), added in 8.0.13. 8.0.x and 8.4.x are both fine. |
| Storage engine | **InnoDB** (default) | Foreign keys, row locks, and `SELECT ... FOR UPDATE` are all required for correct points accounting. |
| Character set | **`utf8mb4`** | Product names and CSV catalog data are free-form text. |
| Collation | **`utf8mb4_0900_ai_ci`** (the 8.0 default) | Deliberate: usernames compare case-insensitively. Identifier columns override this per-column with `utf8mb4_bin` — do not set a server-wide binary collation. |
| `sql_mode` | Default (includes `STRICT_TRANS_TABLES`) | The app assumes over-long values are rejected, not silently truncated. |
| Time zone | Any | The app pins `time_zone = '+00:00'` per connection; the server's own setting is irrelevant. |

MariaDB has **not** been verified and is not supported — its generated-column
and `information_schema` behaviour differs from MySQL 8.

## 2. Create the database and user

```sql
CREATE DATABASE vastra_loyalty
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

CREATE USER 'vastra_loyalty'@'%' IDENTIFIED BY '<strong-password>';
GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, ALTER, INDEX, DROP, REFERENCES
  ON vastra_loyalty.* TO 'vastra_loyalty'@'%';
FLUSH PRIVILEGES;
```

The DDL grants (`CREATE`, `ALTER`, `INDEX`, `REFERENCES`) are **not optional**.
The app runs `init_db()` → `migrate()` → `create_constraints()` on **every**
startup to apply schema changes additively; without them a deploy that adds a
column will start but silently skip the migration. `DROP` is only used by the
seed script.

RDS note: the master user cannot be named `admin` or `rdsadmin`, and RDS does
not grant `SUPER` — nothing here needs it.

## 3. Connection string

Set `DATABASE_URL` in the host's own environment settings (Render's Environment
tab, ECS task definition, etc.). **`.env` files are never deployed** — see
`DEPLOY.md`.

```
DATABASE_URL=mysql://vastra_loyalty:<password>@<host>.rds.amazonaws.com:3306/vastra_loyalty?ssl=true
```

- Scheme: `mysql://` or `mysql+pymysql://`.
- `?ssl=true` enables TLS. To also verify the server certificate, download the
  [RDS CA bundle](https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem)
  into the image and use `?ssl_ca=/path/to/global-bundle.pem` instead.
- Percent-encode any special characters in the password.

If `DATABASE_URL` is left unset the app falls back to a local SQLite file — on a
container that means **data is lost on every redeploy**, so it must be set in
any environment that matters.

A leftover PostgreSQL URL is rejected at boot with an explicit message rather
than failing obscurely later:

> `DATABASE_URL is a PostgreSQL URL, but this app now runs on MySQL.`

## 4. First deploy

1. Set `DATABASE_URL` (plus the other env vars in `DEPLOY.md`: `QR_BASE_URL`,
   `SSO_SECRET`, `VASTRA_API_BASE_URL`, `USE_SAMPLE_PRODUCTS=0`).
2. Start the container. On boot it creates all 14 tables, applies every column
   migration, and adds the indexes, foreign keys and the generated-column unique
   index. This is idempotent — restarting changes nothing.
3. Confirm the schema landed:

   ```sql
   SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = 'vastra_loyalty';                       -- expect 14
   SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = 'vastra_loyalty'
       AND CONSTRAINT_TYPE = 'FOREIGN KEY';                       -- expect 24
   SHOW INDEX FROM points_ledger WHERE Key_name = 'uq_ledger_active_scan_token';
   SHOW COLUMNS FROM points_ledger LIKE 'active_scan_token';
   ```

   If the last two return nothing, the DDL grants are missing (see §2).
4. Seed demo data **once**, if wanted. This is destructive and refuses to run
   without the explicit opt-in:

   ```bash
   DATABASE_URL=mysql://... ALLOW_MYSQL=1 python seed.py
   ```

   `seed.py` rebuilds tables from `SCHEMA` only — it does **not** run the column
   migrations. Restart the app afterwards so `migrate()` re-adds them.
5. Walk the panel (`/panel`) and the retailer webviews (`/web`) to confirm.

## 5. Things worth knowing about this schema

These are consequences of the MySQL port that a DBA looking at the database
should not mistake for accidents.

**Timestamps are `VARCHAR(32)`, not `DATETIME`.** Every `created_at` /
`scanned_at` holds a UTC string in `'YYYY-MM-DD HH:MM:SS'` form. They are
compared and grouped as strings (`substr(scanned_at, 1, 7)` gives the dashboard's
month buckets), which is what keeps the SQL identical across SQLite and MySQL.
Do not "fix" these to `DATETIME` — it would return Python `datetime` objects and
break every comparison and JSON response.

**Identifier columns use `utf8mb4_bin`, everything else the DB default.** QR
tokens, manual codes, session tokens, gift-claim references and SSO
`external_id`s must match exactly; usernames and shop names are deliberately
case-insensitive. A foreign key's collation must match its referent, which is
why `points_ledger.token` is binary too.

**`points_ledger.active_scan_token` is a generated column — never write to it.**
MySQL has no partial indexes, so the rule "at most one *active* scan credit per
QR token" is enforced by
`GENERATED ALWAYS AS (CASE WHEN entry_type = 'scan' THEN token END) STORED` plus
a unique index on it. When a scan is reversed (`entry_type` becomes
`'scan_reversed'`) the column recomputes to NULL, which releases the token so the
rightful retailer can rescan.

**A retailer's balance is `SUM(points)` over `points_ledger`** — there is no
balance column. Never add one; write a ledger row instead.

**The app opens one connection per request** and closes it. There is no pool, so
`max_connections` should comfortably exceed peak concurrent requests, and RDS
Proxy (or an app-side pool) is the natural optimisation if request latency to
the database becomes a concern.

## 6. Schema changes after go-live

Never drop or reseed the production database to apply a change. Schema evolution
is additive and idempotent:

- **New table** → add it to `SCHEMA` in `app/database.py` (`CREATE TABLE IF NOT
  EXISTS`).
- **New column** → append to the `_MIGRATIONS` list. Use `VARCHAR(n)` if the
  column will ever be indexed — MySQL cannot index a bare `TEXT`.
- **New index / constraint** → add to `_INDEXES` or `_MYSQL_CONSTRAINTS`. MySQL
  has no `IF NOT EXISTS` for these, so they are guarded by `information_schema`
  lookups.

`migrate()` and `create_constraints()` run on every startup and apply whatever
is missing.

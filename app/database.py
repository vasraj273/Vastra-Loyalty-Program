"""Persistence layer for the loyalty QR API.

Dual backend: PostgreSQL when DATABASE_URL is set (production / Neon),
SQLite otherwise (zero-setup local development). The rest of the app uses
SQLite-style calls (``?`` placeholders, ``cur.lastrowid``,
``db.executescript``); a thin adapter translates those to psycopg when
running on Postgres, so application code stays backend-agnostic.
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "qr_api.db"
DATABASE_URL = os.environ.get("DATABASE_URL")
IS_PG = bool(DATABASE_URL)

if IS_PG:
    import psycopg
    from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS manufacturers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,   -- pbkdf2 salt$hash (hex)
    display_name TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,  -- 1 = super admin (creates accounts)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token TEXT PRIMARY KEY,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id)
        ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    name TEXT NOT NULL,
    sku TEXT NOT NULL UNIQUE,
    loyalty_points INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS retailers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    name TEXT NOT NULL,
    shop_name TEXT NOT NULL,
    region TEXT NOT NULL,
    phone TEXT,
    lat REAL,   -- auto-filled from region city lookup, manual override allowed
    lng REAL,
    location_source TEXT,  -- 'city' (lookup) | 'gps' (locked from first scan)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schemes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL,  -- YYYY-MM-DD inclusive
    end_date TEXT NOT NULL,    -- YYYY-MM-DD inclusive
    bonus_points INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Products covered by a scheme. No rows for a scheme = covers ALL products.
CREATE TABLE IF NOT EXISTS scheme_products (
    scheme_id INTEGER NOT NULL REFERENCES schemes(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    PRIMARY KEY (scheme_id, product_id)
);

CREATE TABLE IF NOT EXISTS qr_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    -- points promised per code, frozen at generation time (printed boxes
    -- keep their value even if the product's points change later)
    points_per_code INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | saved
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS qr_codes (
    token TEXT PRIMARY KEY,
    manual_code TEXT NOT NULL UNIQUE,  -- 6-char fallback if QR damaged
    batch_id INTEGER NOT NULL REFERENCES qr_batches(id) ON DELETE CASCADE,
    is_parent INTEGER NOT NULL DEFAULT 0,  -- 1 = box code aggregating children
    parent_token TEXT,                     -- child -> its box code
    redeemed_at TEXT,
    redeemed_by INTEGER REFERENCES retailers(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Wallet ledger. entry_type:
--   scan        +points  earned by scanning a code (token/product set)
--   gift_redeem -points  spent claiming a gift
--   refund      +points  gift claim rejected
--   adjustment  +/-      manual correction by manufacturer (note set)
--   transfer    +/-      points moved between retailers (counterparty set)
-- Balance for a retailer = SUM(points). Scan analytics filter entry_type='scan'.
CREATE TABLE IF NOT EXISTS points_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    retailer_id INTEGER NOT NULL REFERENCES retailers(id),
    entry_type TEXT NOT NULL DEFAULT 'scan',
    token TEXT REFERENCES qr_codes(token),
    product_id INTEGER REFERENCES products(id),
    points INTEGER NOT NULL,          -- total = base + bonus for scans
    base_points INTEGER NOT NULL DEFAULT 0,
    bonus_points INTEGER NOT NULL DEFAULT 0,
    scheme_id INTEGER REFERENCES schemes(id),  -- scheme that paid the bonus
    counterparty_retailer_id INTEGER REFERENCES retailers(id),  -- transfers
    note TEXT,                          -- reason for adjustments/transfers/gifts
    created_by INTEGER REFERENCES manufacturers(id),  -- who made a manual entry
    region TEXT,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    points_cost INTEGER NOT NULL,
    image_url TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gift_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    retailer_id INTEGER NOT NULL REFERENCES retailers(id),
    gift_id INTEGER NOT NULL REFERENCES gifts(id),
    points_spent INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    ledger_id INTEGER REFERENCES points_ledger(id),  -- the debit row
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_qr_codes_batch ON qr_codes(batch_id);
CREATE INDEX IF NOT EXISTS idx_qr_codes_parent ON qr_codes(parent_token);
CREATE INDEX IF NOT EXISTS idx_ledger_type ON points_ledger(entry_type);
CREATE INDEX IF NOT EXISTS idx_gift_claims_manuf ON gift_claims(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_ledger_retailer ON points_ledger(retailer_id);
CREATE INDEX IF NOT EXISTS idx_ledger_product ON points_ledger(product_id);
CREATE INDEX IF NOT EXISTS idx_ledger_manuf ON points_ledger(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_products_manuf ON products(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_retailers_manuf ON retailers(manufacturer_id);
"""

# Tables with a serial ``id`` column, for which we emulate sqlite's
# ``cur.lastrowid`` via Postgres ``RETURNING id``.
_ID_TABLES = {"manufacturers", "products", "retailers", "qr_batches",
              "schemes", "gifts", "gift_claims", "points_ledger"}

# All tables, dropped with CASCADE on reset (order irrelevant).
_DROP_ORDER = ("gift_claims", "gifts", "points_ledger", "qr_codes",
               "qr_batches", "scheme_products", "schemes", "retailers",
               "products", "auth_tokens", "manufacturers")


# ---------------------------------------------------------------- Postgres

def _pg_schema() -> str:
    s = SCHEMA
    s = s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    s = re.sub(r"\bREAL\b", "DOUBLE PRECISION", s)
    s = s.replace("(datetime('now'))",
                  "(to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))")
    return s


def _translate(sql: str, named: bool) -> str:
    """Rewrite sqlite SQL fragments to their Postgres equivalents."""
    sql = sql.replace("datetime('now')",
                      "to_char(now(), 'YYYY-MM-DD HH24:MI:SS')")
    sql = sql.replace("date('now')", "to_char(now(), 'YYYY-MM-DD')")
    if named:
        # :name -> %(name)s  (only when params is a dict; such queries carry
        # no time-format literals, so colons here are always placeholders)
        sql = re.sub(r":([a-zA-Z]\w*)", r"%(\1)s", sql)
    else:
        sql = sql.replace("?", "%s")
    return sql


class _Cursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class _PGConn:
    """Adapter giving a psycopg connection the sqlite-style surface the app
    expects: ``execute`` returning a cursor with ``lastrowid``,
    ``executemany`` and ``executescript``."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        named = isinstance(params, dict)
        psql = _translate(sql, named)
        m = re.match(r"\s*insert\s+into\s+(\w+)", psql, re.IGNORECASE)
        want_id = (m and m.group(1).lower() in _ID_TABLES
                   and "returning" not in psql.lower())
        if want_id:
            psql = psql.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor()
        try:
            cur.execute(psql, params)
        except psycopg.errors.UniqueViolation as exc:
            # Surface as the sqlite-style message the app already checks for.
            raise Exception(f"UNIQUE constraint failed: {exc}") from exc
        if want_id:
            row = cur.fetchone()
            return _Cursor(cur, lastrowid=row["id"] if row else None)
        return _Cursor(cur)

    def executemany(self, sql, seq):
        cur = self._conn.cursor()
        cur.executemany(_translate(sql, False), list(seq))
        return _Cursor(cur)

    def executescript(self, script):
        cur = self._conn.cursor()
        for stmt in script.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        return _Cursor(cur)


# ---------------------------------------------------------------- public API

def init_db() -> None:
    with get_db() as db:
        db.executescript(_pg_schema() if IS_PG else SCHEMA)


def reset_db() -> None:
    """Drop everything and recreate the schema. Used by the seed script;
    never called at app startup, so production data persists across deploys."""
    if IS_PG:
        with get_db() as db:
            db.executescript(
                "DROP TABLE IF EXISTS "
                + ", ".join(_DROP_ORDER) + " CASCADE")
    elif DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


@contextmanager
def get_db():
    if IS_PG:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row,
                               autocommit=False)
        try:
            yield _PGConn(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

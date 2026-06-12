"""SQLite persistence layer for the loyalty QR API."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "qr_api.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS manufacturers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,   -- pbkdf2: salt$hash (hex)
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
    redeemed_at TEXT,
    redeemed_by INTEGER REFERENCES retailers(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS points_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    retailer_id INTEGER NOT NULL REFERENCES retailers(id),
    token TEXT NOT NULL REFERENCES qr_codes(token),
    product_id INTEGER NOT NULL REFERENCES products(id),
    points INTEGER NOT NULL,          -- total = base + bonus
    base_points INTEGER NOT NULL DEFAULT 0,
    bonus_points INTEGER NOT NULL DEFAULT 0,
    scheme_id INTEGER REFERENCES schemes(id),  -- scheme that paid the bonus
    region TEXT NOT NULL,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_qr_codes_batch ON qr_codes(batch_id);
CREATE INDEX IF NOT EXISTS idx_ledger_retailer ON points_ledger(retailer_id);
CREATE INDEX IF NOT EXISTS idx_ledger_product ON points_ledger(product_id);
CREATE INDEX IF NOT EXISTS idx_ledger_manuf ON points_ledger(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_products_manuf ON products(manufacturer_id);
CREATE INDEX IF NOT EXISTS idx_retailers_manuf ON retailers(manufacturer_id);
"""


def init_db() -> None:
    with get_db() as db:
        db.executescript(SCHEMA)


@contextmanager
def get_db():
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

"""Shared pytest fixtures.

Rate limiting is disabled (RL_ENABLED=0) for deterministic functional tests;
the dedicated test_rate_limit.py re-enables it with a low limit in isolation.
By default the app is pointed at a throwaway SQLite file and every test starts
from clean tables.

Setting DATABASE_URL runs the same suite against MySQL instead (point it at a
throwaway database — the clean fixture wipes every table), and additionally
un-skips the two MySQL-only proofs: test_race_mysql.py (concurrency) and
test_mysql_schema.py (DDL idempotency, generated-column index, collation).

    DATABASE_URL=mysql://user:pass@127.0.0.1:3306/vl_test pytest tests/ -q
"""
import os

os.environ.setdefault("RL_ENABLED", "0")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def appmod(tmp_path_factory):
    """Import the app once, pointed at a temp SQLite DB."""
    import app.database as d
    d.DB_PATH = tmp_path_factory.mktemp("vl") / "test.db"
    import app.main as m
    # Run startup (init_db + migrate + create_constraints) once.
    d.init_db(); d.migrate(); d.create_constraints()
    return m


@pytest.fixture()
def db(appmod):
    from app.database import get_db
    return get_db


@pytest.fixture(autouse=True)
def clean(appmod):
    """Wipe data before each test so they don't interfere."""
    from app.database import get_db
    # Child tables first so foreign keys are satisfied during teardown.
    with get_db() as conn:
        for t in ("gift_claims", "points_ledger", "qr_codes", "qr_batches",
                  "scheme_products", "schemes", "retailer_tokens", "gifts",
                  "retailers", "distributors", "products", "product_points",
                  "auth_tokens", "manufacturers"):
            conn.execute(f"DELETE FROM {t}")
    yield


@pytest.fixture()
def client(appmod):
    from starlette.testclient import TestClient
    with TestClient(appmod.app) as c:
        yield c


@pytest.fixture()
def seed(appmod):
    """Insert a manufacturer + product + one child QR + a retailer login, and
    return identifiers and a retailer bearer token. Uses the app's real helpers
    so hashing/login derivation match production."""
    from app.database import get_db
    from app.auth import hash_password, issue_retailer_token

    data = {}
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO manufacturers (username, password_hash, display_name, is_admin)"
            " VALUES (?, ?, ?, 0)",
            ("acme", hash_password("acmepass"), "Acme Mills"))
        mid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO products (manufacturer_id, name, sku, loyalty_points)"
            " VALUES (?, ?, ?, ?)", (mid, "Saree", "SKU-1", 10))
        pid = cur.lastrowid
        # manufacturer_id is required: under the Product SoR model batch tenancy
        # lives on qr_batches, and _redeem_code rejects a scan whose batch
        # manufacturer does not match the retailer's (uniform 404).
        cur = conn.execute(
            "INSERT INTO qr_batches (product_id, quantity, points_per_code,"
            " manufacturer_id) VALUES (?, ?, ?, ?)", (pid, 1, 10, mid))
        bid = cur.lastrowid
        conn.execute(
            "INSERT INTO qr_codes (token, manual_code, batch_id, is_parent, parent_token)"
            " VALUES (?, ?, ?, 0, NULL)", ("TOKCHILD", "AAAAAA", bid))
        cur = conn.execute(
            "INSERT INTO retailers (manufacturer_id, name, shop_name, region,"
            " username, password_hash, must_change) VALUES (?,?,?,?,?,?,1)",
            (mid, "Ravi", "Ravi Shop", "Surat", "ravi",
             hash_password("TempPass123")))
        rid = cur.lastrowid
        rtoken = issue_retailer_token(conn, rid)
    data.update(mid=mid, pid=pid, bid=bid, rid=rid, rtoken=rtoken,
                token="TOKCHILD", manual="AAAAAA")
    return data

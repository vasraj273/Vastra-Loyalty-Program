"""Standalone concurrency proof for Fix 1 (scan) and Fix 2 (claim) against a
REAL PostgreSQL backend, driving the REAL HTTP endpoints through a live uvicorn
server with genuinely concurrent client threads.

Run directly (not via the shared pytest session, so it gets a clean PG-bound
import):  DATABASE_URL=postgresql://... python tests/_pg_race_runner.py

Exits 0 on success, non-zero (with a message) on any failure. Imported and
invoked as a subprocess by test_race_postgres.py.
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("RL_ENABLED", "0")  # isolate the race, not the limiter

assert os.environ.get("DATABASE_URL"), "DATABASE_URL must be set for the PG proof"

import httpx  # noqa: E402
import uvicorn  # noqa: E402

import app.database as d  # noqa: E402
from app.auth import hash_password, issue_retailer_token  # noqa: E402

assert d.IS_PG, "expected Postgres backend (DATABASE_URL set)"

from app.main import app  # noqa: E402

PORT = int(os.environ.get("PG_PROOF_PORT", "8099"))
BASE = f"http://127.0.0.1:{PORT}"
N = 20


def reset_and_seed():
    d.init_db(); d.migrate(); d.create_constraints()
    with d.get_db() as db:
        for t in ("gift_claims", "points_ledger", "qr_codes", "qr_batches",
                  "scheme_products", "schemes", "retailer_tokens", "gifts",
                  "retailers", "distributors", "products", "auth_tokens",
                  "manufacturers"):
            db.execute(f"DELETE FROM {t}")
        cur = db.execute(
            "INSERT INTO manufacturers (username, password_hash, display_name, is_admin)"
            " VALUES (?,?,?,0)", ("acme", hash_password("p"), "Acme"))
        mid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO products (manufacturer_id, name, sku, loyalty_points)"
            " VALUES (?,?,?,?)", (mid, "Saree", "SKU-1", 10))
        pid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO qr_batches (product_id, quantity, points_per_code)"
            " VALUES (?,?,?)", (pid, 1, 10))
        bid = cur.lastrowid
        db.execute(
            "INSERT INTO qr_codes (token, manual_code, batch_id, is_parent, parent_token)"
            " VALUES (?,?,?,0,NULL)", ("RACETOKEN", "RACE01", bid))
        cur = db.execute(
            "INSERT INTO retailers (manufacturer_id, name, shop_name, region,"
            " username, password_hash, must_change) VALUES (?,?,?,?,?,?,0)",
            (mid, "R", "Race Shop", "Surat", "race", hash_password("x")))
        rid = cur.lastrowid
        rtoken = issue_retailer_token(db, rid)
        # Wallet pre-loaded with exactly one gift's worth of points.
        db.execute(
            "INSERT INTO points_ledger (manufacturer_id, retailer_id, entry_type, points)"
            " VALUES (?,?, 'scan', 100)", (mid, rid))
        cur = db.execute(
            "INSERT INTO gifts (manufacturer_id, name, description, points_cost, active)"
            " VALUES (?,?,?,?,1)", (mid, "Gift", "", 100))
        gid = cur.lastrowid
    return mid, rid, rtoken, gid


def fire(path, json_body, token):
    headers = {"Authorization": f"Bearer {token}"}
    def one(_):
        with httpx.Client(base_url=BASE, timeout=30) as c:
            return c.post(path, json=json_body, headers=headers).status_code
    with ThreadPoolExecutor(max_workers=N) as ex:
        return list(ex.map(one, range(N)))


def ledger_rows_for(token):
    with d.get_db() as db:
        return db.execute(
            "SELECT COUNT(*) AS n FROM points_ledger WHERE token = ?", (token,)
        ).fetchone()["n"]


def balance(rid):
    with d.get_db() as db:
        return db.execute(
            "SELECT COALESCE(SUM(points),0) AS b FROM points_ledger WHERE retailer_id = ?",
            (rid,)).fetchone()["b"]


def main():
    mid, rid, rtoken, gid = reset_and_seed()

    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    failures = []
    try:
        # ---- Fix 1: 20 concurrent scans of ONE code ----
        codes = fire("/scan", {"code": "RACETOKEN"}, rtoken)
        ok = codes.count(200)
        rows = ledger_rows_for("RACETOKEN")
        print(f"[scan] 200s={ok} 409s={codes.count(409)} ledger_rows={rows}")
        if ok != 1:
            failures.append(f"scan: expected exactly 1 success, got {ok}")
        if rows != 1:
            failures.append(f"scan: expected exactly 1 ledger row, got {rows}")

        # ---- Fix 2: 20 concurrent claims with balance for ONE ----
        bal_before = balance(rid)
        claim_codes = fire("/retailer/claim", {"gift_id": gid}, rtoken)
        successes = claim_codes.count(201)
        bal_after = balance(rid)
        print(f"[claim] 201s={successes} 409s={claim_codes.count(409)} "
              f"balance {bal_before}->{bal_after}")
        if successes != 1:
            failures.append(f"claim: expected exactly 1 success, got {successes}")
        if bal_after < 0:
            failures.append(f"claim: wallet went negative ({bal_after})")
    finally:
        server.should_exit = True
        th.join(timeout=10)

    if failures:
        print("FAIL:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("PASS: single reward + single claim under 20x concurrency on Postgres")


if __name__ == "__main__":
    main()

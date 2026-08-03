"""MySQL schema/DDL proof. See test_mysql_schema.py for what and why.

Run directly:  DATABASE_URL=mysql://... python tests/_mysql_schema_runner.py
Exits 0 on success, non-zero (with a message) on any failure.

DESTRUCTIVE: drops and rebuilds every table in the target database. Point it at
a throwaway MySQL database, never at production.
"""
import os
import sys

os.environ.setdefault("RL_ENABLED", "0")

assert os.environ.get("DATABASE_URL"), "DATABASE_URL must be set"

import app.database as d  # noqa: E402
from app.auth import hash_password  # noqa: E402

assert d.IS_MYSQL, "expected MySQL backend (DATABASE_URL set)"

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def indexes(table):
    with d.get_db() as db:
        return d._mysql_indexes(db, table)


def columns(table):
    with d.get_db() as db:
        return d._mysql_columns(db, table)


def startup():
    """Exactly what app.main runs on boot."""
    d.init_db()
    d.migrate()
    d.create_constraints()


def snapshot():
    """Full index + column inventory, to prove a second boot changes nothing."""
    tables = ("manufacturers", "retailers", "points_ledger", "qr_codes",
              "qr_batches", "gift_claims", "product_points", "products",
              "distributors", "schemes", "gifts", "auth_tokens",
              "retailer_tokens", "scheme_products")
    return {t: (sorted(indexes(t)), sorted(columns(t))) for t in tables}


def seed_minimal():
    with d.get_db() as db:
        cur = db.execute(
            "INSERT INTO manufacturers (username, password_hash, display_name,"
            " is_admin) VALUES (?,?,?,0)", ("acme", hash_password("p"), "Acme"))
        mid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO retailers (manufacturer_id, name, shop_name, region)"
            " VALUES (?,?,?,?)", (mid, "R", "Race Shop", "Surat"))
        rid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO qr_batches (quantity, points_per_code, manufacturer_id)"
            " VALUES (?,?,?)", (1, 10, mid))
        bid = cur.lastrowid
        db.execute(
            "INSERT INTO qr_codes (token, manual_code, batch_id, is_parent)"
            " VALUES (?,?,?,0)", ("tok0001", "AAAAAA", bid))
    return mid, rid


def main():
    # ---- 1. DDL idempotency: two consecutive boots must be identical ----
    d.reset_db()
    startup()
    first = snapshot()
    startup()                      # second deploy against an existing database
    second = snapshot()
    for t in first:
        check(first[t] == second[t],
              f"idempotency: {t} changed on the second startup\n"
              f"    first={first[t]}\n   second={second[t]}")
    print(f"[ddl] two startups produced identical schema across "
          f"{len(first)} tables")

    # Every guard we expect must actually exist (create_constraints swallows
    # exceptions, so absence would otherwise be invisible).
    for table, name in (("points_ledger", "uq_ledger_active_scan_token"),
                        ("manufacturers", "uq_manuf_external"),
                        ("retailers", "uq_retailer_external"),
                        ("qr_batches", "idx_qr_batches_manuf"),
                        ("points_ledger", "idx_ledger_product_ext"),
                        ("qr_codes", "idx_qr_codes_batch"),
                        ("points_ledger", "idx_ledger_retailer")):
        check(name in indexes(table), f"missing index {name} on {table}")
    check("active_scan_token" in columns("points_ledger"),
          "missing generated column points_ledger.active_scan_token")
    print("[ddl] all constraints and indexes present")

    # Every inline REFERENCES in SCHEMA must exist as a real MySQL constraint.
    # MySQL parses inline references and creates nothing, so without the
    # table-level rewrite these all vanish silently.
    expected_fks = list(d._mysql_foreign_keys())
    check(len(expected_fks) > 0, "no foreign keys derived from SCHEMA")
    for table, name, _ddl in expected_fks:
        with d.get_db() as db:
            check(name in d._mysql_foreign_key_names(db, table),
                  f"missing foreign key {name} on {table}")
    print(f"[fk] all {len(expected_fks)} foreign keys created")

    # ...and they must actually bite: ON DELETE CASCADE fires, and a child row
    # pointing at a missing parent is refused.
    with d.get_db() as db:
        cur = db.execute(
            "INSERT INTO manufacturers (username, password_hash, display_name,"
            " is_admin) VALUES (?,?,?,0)", ("fktest", hash_password("p"), "FK"))
        fk_mid = cur.lastrowid
        db.execute("INSERT INTO auth_tokens (token, manufacturer_id)"
                   " VALUES (?,?)", ("fk-token-1", fk_mid))
    with d.get_db() as db:
        db.execute("DELETE FROM manufacturers WHERE id = ?", (fk_mid,))
    with d.get_db() as db:
        left = db.execute("SELECT COUNT(*) AS n FROM auth_tokens"
                          " WHERE token = ?", ("fk-token-1",)).fetchone()["n"]
    check(left == 0, "ON DELETE CASCADE did not remove the orphaned auth_token")

    orphan = None
    try:
        with d.get_db() as db:
            db.execute("INSERT INTO auth_tokens (token, manufacturer_id)"
                       " VALUES (?,?)", ("fk-token-2", 99999999))
    except Exception as exc:
        orphan = str(exc)
    check(orphan is not None,
          "a token referencing a non-existent manufacturer was accepted")
    print("[fk] cascade delete fires and orphan inserts are refused")

    mid, rid = seed_minimal()

    # ---- 2. generated column == the Postgres partial unique index ----
    with d.get_db() as db:
        db.execute(
            "INSERT INTO points_ledger (manufacturer_id, retailer_id,"
            " entry_type, token, points) VALUES (?,?,'scan',?,10)",
            (mid, rid, "tok0001"))
    dup = None
    try:
        with d.get_db() as db:
            db.execute(
                "INSERT INTO points_ledger (manufacturer_id, retailer_id,"
                " entry_type, token, points) VALUES (?,?,'scan',?,10)",
                (mid, rid, "tok0001"))
    except Exception as exc:
        dup = str(exc)
    check(dup is not None, "a second active scan for one token was allowed")
    check(dup is not None and "UNIQUE constraint failed" in dup,
          f"duplicate scan raised the wrong message: {dup!r}")
    print("[gencol] second active scan on the same token rejected")

    # A non-'scan' row sharing the token is fine (reversal bookkeeping).
    with d.get_db() as db:
        db.execute(
            "INSERT INTO points_ledger (manufacturer_id, retailer_id,"
            " entry_type, token, points) VALUES (?,?,'reversal',?,-10)",
            (mid, rid, "tok0001"))
    print("[gencol] reversal row sharing the token accepted")

    # Reversing the scan must free the token for a legitimate rescan.
    with d.get_db() as db:
        db.execute("UPDATE points_ledger SET entry_type = 'scan_reversed'"
                   " WHERE entry_type = 'scan' AND token = ?", ("tok0001",))
    rescan_err = None
    try:
        with d.get_db() as db:
            db.execute(
                "INSERT INTO points_ledger (manufacturer_id, retailer_id,"
                " entry_type, token, points) VALUES (?,?,'scan',?,10)",
                (mid, rid, "tok0001"))
    except Exception as exc:
        rescan_err = str(exc)
    check(rescan_err is None,
          f"rescan after reversal was blocked: {rescan_err}")
    print("[gencol] token freed for rescan after reversal")

    # ---- 3. collation split ----
    # Identifier columns are case-SENSITIVE (binary), as on SQLite today.
    with d.get_db() as db:
        row = db.execute("SELECT token FROM qr_codes WHERE token = ?",
                         ("TOK0001",)).fetchone()
    check(row is None, "qr_codes.token matched case-insensitively "
                       "(expected utf8mb4_bin)")
    with d.get_db() as db:
        row = db.execute("SELECT token FROM qr_codes WHERE token = ?",
                         ("tok0001",)).fetchone()
    check(row is not None, "qr_codes.token exact-case lookup failed")
    print("[collation] tokens compare case-sensitively")

    # Usernames are case-INSENSITIVE, so 'ACME' collides with 'acme'.
    clash = None
    try:
        with d.get_db() as db:
            db.execute(
                "INSERT INTO manufacturers (username, password_hash,"
                " display_name, is_admin) VALUES (?,?,?,0)",
                ("ACME", hash_password("p"), "Acme Caps"))
    except Exception as exc:
        clash = str(exc)
    check(clash is not None and "UNIQUE constraint failed" in clash,
          "username 'ACME' did not collide with 'acme' (expected "
          "case-insensitive collation)")
    print("[collation] usernames compare case-insensitively")

    # ---- 4. timestamps are UTC strings in the app's exact format ----
    with d.get_db() as db:
        ts = db.execute("SELECT datetime('now') AS now,"
                        " date('now') AS today").fetchone()
    check(len(ts["now"]) == 19 and ts["now"][4] == "-" and ts["now"][13] == ":",
          f"datetime('now') is not 'YYYY-MM-DD HH:MM:SS': {ts['now']!r}")
    check(len(ts["today"]) == 10, f"date('now') is not 'YYYY-MM-DD': {ts['today']!r}")
    check(ts["now"].startswith(ts["today"]),
          f"date/datetime disagree: {ts['today']!r} vs {ts['now']!r}")
    import datetime as _dt
    utc_now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    check(abs((_dt.datetime.fromisoformat(ts["now"])
               - _dt.datetime.fromisoformat(utc_now)).total_seconds()) < 120,
          f"MySQL clock is not UTC: got {ts['now']!r}, expected ~{utc_now!r}")
    print(f"[time] datetime('now') -> {ts['now']!r} (UTC, sqlite format)")

    if failures:
        print("FAIL:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("PASS: MySQL DDL idempotent, generated-column index correct, "
          "collation split correct, timestamps UTC")


if __name__ == "__main__":
    main()

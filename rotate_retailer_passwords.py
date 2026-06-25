"""Rotate existing retailer passwords off the old predictable scheme (Fix 3).

Retailers created before this fix had a deterministic password (<username>123)
that anyone could guess from the shop name. This one-off, non-destructive script
resets every retailer login (or a chosen subset) to a fresh cryptographically
random temporary password, flags must_change=1, and prints the new credentials
once so they can be redistributed. Usernames are left unchanged so nothing else
breaks. Logins keep working — with the new password.

It does NOT touch points, scans, claims, or any other data.

Usage:
    # dry run — list who WOULD be rotated, change nothing
    python rotate_retailer_passwords.py --dry-run

    # rotate everyone (local SQLite)
    python rotate_retailer_passwords.py

    # rotate everyone on Neon/Postgres
    DATABASE_URL=postgresql://... python rotate_retailer_passwords.py

    # rotate a single manufacturer's retailers
    python rotate_retailer_passwords.py --manufacturer-id 3
"""
import argparse

from app.auth import hash_password, new_temp_password
from app.database import get_db, init_db, migrate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="show who would be rotated without changing anything")
    ap.add_argument("--manufacturer-id", type=int, default=None,
                    help="limit rotation to one manufacturer's retailers")
    args = ap.parse_args()

    init_db()
    migrate()
    where = "WHERE username IS NOT NULL"
    params: list = []
    if args.manufacturer_id is not None:
        where += " AND manufacturer_id = ?"
        params.append(args.manufacturer_id)

    rotated = []
    with get_db() as db:
        rows = db.execute(
            f"SELECT id, username, shop_name FROM retailers {where} ORDER BY id",
            params,
        ).fetchall()
        for r in rows:
            if args.dry_run:
                # No writes — the transaction commits nothing.
                rotated.append((r["username"], "(unchanged)", r["shop_name"]))
                continue
            password = new_temp_password()
            db.execute(
                "UPDATE retailers SET password_hash = ?, must_change = 1 "
                "WHERE id = ?",
                (hash_password(password), r["id"]),
            )
            rotated.append((r["username"], password, r["shop_name"]))

    _report(rotated, dry=args.dry_run)


def _report(rotated, dry: bool) -> None:
    if not rotated:
        print("No retailer logins matched; nothing to do.")
        return
    verb = "Would rotate" if dry else "Rotated"
    print(f"{verb} {len(rotated)} retailer login(s):")
    for uname, password, shop in rotated:
        print(f"  {uname} / {password}   ({shop})")
    if not dry:
        print("\nHand these temporary passwords to each retailer; they will be "
              "prompted to change on next login (must_change=1).")


if __name__ == "__main__":
    main()

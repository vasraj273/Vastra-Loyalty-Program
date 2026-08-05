"""Create a super admin (and optionally one manufacturer) without wiping anything.

`seed.py` is destructive — it drops every table — so it must never be pointed at
a database that already holds real data. But a freshly provisioned RDS instance
has no accounts at all: the app's startup only creates and migrates tables, it
never seeds, so nobody can log into /panel. This script fills exactly that gap.

Non-destructive and idempotent: it ensures the schema (init_db + migrate +
create_constraints), then inserts only the accounts that don't already exist.
An existing username is left completely untouched — rerunning changes nothing
and never resets a password.

Usage (local SQLite):
    python bootstrap_admin.py --admin-user admin --admin-pass 'S0me-Long-Pass'

Usage (MySQL / RDS) — no ALLOW_MYSQL needed, nothing is dropped:
    export DATABASE_URL='mysql://user:pass@host:3306/db?ssl=true'
    python bootstrap_admin.py --admin-user admin --admin-pass 'S0me-Long-Pass'

Optionally also create a password-login manufacturer, as a fallback for when
Vastra OTP login isn't reachable yet (Vastra OTP auto-provisions its own
manufacturer row, so this is only a backstop):
    python bootstrap_admin.py --admin-user admin --admin-pass '...' \
        --mfr-user acme --mfr-pass '...' --mfr-name 'Acme Textiles'

Passwords are read from the argument, or prompted for if omitted, so they need
not appear in shell history.
"""

import argparse
import getpass
import sys

from app.auth import hash_password
from app.database import create_constraints, get_db, init_db, migrate


def _upsert(db, username: str, password: str, display_name: str,
            is_admin: int) -> str:
    """Insert the account if the username is free. Returns a status line."""
    uname = username.strip().lower()
    if not uname:
        return "  (skipped: blank username)"
    existing = db.execute(
        "SELECT id, is_admin FROM manufacturers WHERE username = ?", (uname,)
    ).fetchone()
    if existing:
        kind = "super admin" if existing["is_admin"] else "manufacturer"
        return f"  {uname!r} already exists ({kind}, id={existing['id']}) - untouched"
    cur = db.execute(
        """INSERT INTO manufacturers
           (username, password_hash, display_name, is_admin)
           VALUES (?, ?, ?, ?)""",
        (uname, hash_password(password), display_name, is_admin),
    )
    kind = "super admin" if is_admin else "manufacturer"
    return f"  created {kind} {uname!r} (id={cur.lastrowid})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--admin-user", default="admin")
    ap.add_argument("--admin-pass")
    ap.add_argument("--admin-name", default="Super Admin")
    ap.add_argument("--mfr-user", help="optional password-login manufacturer")
    ap.add_argument("--mfr-pass")
    ap.add_argument("--mfr-name", default="")
    args = ap.parse_args()

    admin_pass = args.admin_pass or getpass.getpass(
        f"Password for super admin {args.admin_user!r}: ")
    if len(admin_pass) < 8:
        print("Refusing: admin password must be at least 8 characters.",
              file=sys.stderr)
        return 2

    mfr_pass = None
    if args.mfr_user:
        mfr_pass = args.mfr_pass or getpass.getpass(
            f"Password for manufacturer {args.mfr_user!r}: ")
        if len(mfr_pass) < 8:
            print("Refusing: manufacturer password must be at least 8 "
                  "characters.", file=sys.stderr)
            return 2

    # Same startup DDL the app runs, so this works against an empty database.
    init_db()
    migrate()
    create_constraints()

    print("Bootstrapping accounts:")
    with get_db() as db:
        print(_upsert(db, args.admin_user, admin_pass, args.admin_name, 1))
        if args.mfr_user:
            print(_upsert(db, args.mfr_user, mfr_pass,
                          args.mfr_name or args.mfr_user.title(), 0))
    print("Done. Log in at /panel/ - nothing else was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

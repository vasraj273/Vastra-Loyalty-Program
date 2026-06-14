"""Give existing retailers a login without wiping any data.

Non-destructive: ensures the schema (init_db + migrate), then for every
retailer that has no username yet, assigns one derived from the shop name
(first word, lowercased) with password <username>123. Collisions get the
retailer id appended. Safe to run repeatedly; already-set logins are skipped.

Usage (local SQLite):   python backfill_retailer_logins.py
Usage (Neon/Postgres):  set DATABASE_URL, then run the same command.
"""

from app.auth import hash_password
from app.database import get_db, init_db, migrate


def main() -> None:
    init_db()
    migrate()
    done = []
    with get_db() as db:
        taken = {
            r["username"] for r in db.execute(
                "SELECT username FROM retailers WHERE username IS NOT NULL")
        }
        rows = db.execute(
            "SELECT id, shop_name FROM retailers WHERE username IS NULL"
        ).fetchall()
        for r in rows:
            base = (r["shop_name"].split() or ["shop"])[0].lower()
            uname = base
            if uname in taken:
                uname = f"{base}{r['id']}"
            taken.add(uname)
            db.execute(
                "UPDATE retailers SET username = ?, password_hash = ? "
                "WHERE id = ?",
                (uname, hash_password(uname + "123"), r["id"]),
            )
            done.append((uname, r["shop_name"]))

    if not done:
        print("All retailers already have logins; nothing to do.")
        return
    print(f"Set logins for {len(done)} retailer(s):")
    for uname, shop in done:
        print(f"  {uname} / {uname}123   ({shop})")


if __name__ == "__main__":
    main()

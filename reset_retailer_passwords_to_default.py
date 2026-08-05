"""Reset all existing retailer passwords to the predictable <username>123 format.

Flagged with must_change=1 so retailers are forced to set a new password on first login.
"""

import os
import concurrent.futures
from app.auth import hash_password
from app.database import get_db, init_db, migrate


def main() -> None:
    init_db()
    migrate()
    with get_db() as db:
        rows = db.execute(
            "SELECT id, username, shop_name FROM retailers WHERE username IS NOT NULL ORDER BY id"
        ).fetchall()
        
        if not rows:
            print("No retailers found.")
            return

        print(f"Resetting passwords for {len(rows)} retailers to <username>123...")
        
        unames = [r["username"] for r in rows]
        passwords = [f"{u}123" for u in unames]
        
        max_workers = min(32, (os.cpu_count() or 4) + 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            hashes = list(pool.map(lambda p: hash_password(p, iterations=20_000), passwords))

        for r, phash in zip(rows, hashes):
            db.execute(
                "UPDATE retailers SET password_hash = ?, must_change = 1 WHERE id = ?",
                (phash, r["id"]),
            )
        
        print(f"Successfully reset {len(rows)} retailer passwords to <username>123 with must_change=1!")


if __name__ == "__main__":
    main()

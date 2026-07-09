"""Additive demo data: 5 more manufacturers with 10 retailers each.

Does NOT touch existing rows or call reset_db() - purely additive INSERTs.
Works against local SQLite (default) or Postgres/Neon if DATABASE_URL is set
in the environment - since writing test data to the live production DB is
risky, that path requires ALLOW_NEON=1 as an explicit opt-in.

Run (local):  .venv\\Scripts\\python seed_extra.py
Run (Neon):   DATABASE_URL=... ALLOW_NEON=1 python3 seed_extra.py
"""

import os
import random

from app.auth import hash_password
from app.database import IS_PG, get_db
from app.main import _assign_retailer_login
from app.geo import coords_for

if IS_PG and os.environ.get("ALLOW_NEON") != "1":
    raise SystemExit(
        "DATABASE_URL is set (Postgres/Neon) but ALLOW_NEON=1 was not passed - "
        "refusing to run against production without explicit opt-in."
    )

random.seed(42)

MANUFACTURERS = [
    ("rangoli", "Rangoli Fabrics"),
    ("kashi", "Kashi Handlooms"),
    ("indus", "Indus Textiles"),
    ("shakti", "Shakti Weaves"),
    ("mystic", "Mystic Threads"),
]

RETAILER_NAMES = [
    ("Ravi Malhotra", "Malhotra Sarees", "Jaipur"),
    ("Neha Kapoor", "Kapoor Cloth House", "Delhi"),
    ("Sanjay Mehta", "Mehta Textiles", "Mumbai"),
    ("Pooja Chawla", "Chawla Fabrics", "Ludhiana"),
    ("Amit Trivedi", "Trivedi Sarees", "Ahmedabad"),
    ("Rekha Pillai", "Pillai Silks", "Kochi"),
    ("Vinod Gupta", "Gupta Vastra Bhandar", "Varanasi"),
    ("Shalini Rao", "Rao Fabrics", "Bengaluru"),
    ("Manoj Tiwari", "Tiwari Cloth Stores", "Lucknow"),
    ("Divya Menon", "Menon Textiles", "Chennai"),
]


def main() -> None:
    with get_db() as db:
        for username, display in MANUFACTURERS:
            if db.execute(
                "SELECT 1 FROM manufacturers WHERE username = ?", (username,)
            ).fetchone():
                print(f"skip {username} (already exists)")
                continue

            cur = db.execute(
                """INSERT INTO manufacturers
                   (username, password_hash, display_name, is_admin)
                   VALUES (?, ?, ?, 0)""",
                (username, hash_password(username + "123"), display),
            )
            mid = cur.lastrowid

            for name, shop, city in RETAILER_NAMES:
                lat, lng = coords_for(city)
                cur = db.execute(
                    """INSERT INTO retailers
                       (manufacturer_id, name, shop_name, region, phone,
                        lat, lng, location_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'city')""",
                    (mid, name, shop, city,
                     f"98{random.randint(10000000, 99999999)}", lat, lng),
                )
                rid = cur.lastrowid
                r_username, r_password = _assign_retailer_login(db, shop, rid)
                print(f"  retailer {r_username}/{r_password} ({shop}, {city})")

            print(f"manufacturer {username}/{username}123 -> {display} (id {mid})")


if __name__ == "__main__":
    main()

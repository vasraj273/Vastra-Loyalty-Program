"""Bulk-import retailer logins from a CSV file.

This is an offline admin tool — run it from the terminal, not the website.
Real manufacturers use it (or the company runs it for them) to onboard many
retailers at once instead of adding them one by one in the panel.

CSV columns (header row required):
    manufacturer_username, name, shop_name, region, phone, username, password

- manufacturer_username : the manufacturer the retailer belongs to (e.g. surya)
- name                  : shop owner's name
- shop_name             : shop name
- region                : city (coordinates auto-resolved for the map)
- phone                 : optional
- username, password    : the retailer's login for YourApp (/web)

Coordinates are filled from the city lookup. Rows whose username already
exists are skipped. Targets the configured database (SQLite locally, or the
MySQL server in DATABASE_URL).

Usage:
    python import_retailers.py sample_retailers.csv
"""

import csv
import sys

from app.auth import hash_password
from app.database import get_db, init_db
from app.geo import coords_for

REQUIRED = {"manufacturer_username", "name", "shop_name", "region", "username",
            "password"}


def main(path: str) -> None:
    init_db()  # ensure tables exist; never wipes
    created = skipped = 0
    errors = []

    with get_db() as db, open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"CSV is missing required columns: {', '.join(missing)}")

        manuf_cache = {}
        for i, row in enumerate(reader, start=2):  # row 1 is the header
            row = {k: (v or "").strip() for k, v in row.items()}
            muser = row["manufacturer_username"].lower()
            uname = row["username"].lower()
            if not (muser and uname and row["password"]
                    and row["shop_name"] and row["region"]):
                errors.append(f"row {i}: missing a required value")
                continue

            if muser not in manuf_cache:
                m = db.execute(
                    "SELECT id FROM manufacturers WHERE username = ?",
                    (muser,),
                ).fetchone()
                manuf_cache[muser] = m["id"] if m else None
            mid = manuf_cache[muser]
            if mid is None:
                errors.append(f"row {i}: manufacturer '{muser}' not found")
                continue

            exists = db.execute(
                "SELECT 1 FROM retailers WHERE username = ?", (uname,)
            ).fetchone()
            if exists:
                skipped += 1
                continue

            coords = coords_for(row["region"])
            lat, lng = coords if coords else (None, None)
            db.execute(
                """INSERT INTO retailers
                   (manufacturer_id, name, shop_name, region, phone,
                    username, password_hash, lat, lng, location_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, row["name"], row["shop_name"], row["region"],
                 row.get("phone") or None, uname,
                 hash_password(row["password"]), lat, lng,
                 "city" if coords else None),
            )
            created += 1

    print(f"Imported {created} retailer(s); skipped {skipped} existing.")
    for e in errors:
        print("  -", e)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python import_retailers.py <file.csv>")
    main(sys.argv[1])

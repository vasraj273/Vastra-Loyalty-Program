"""Demo data: super admin + two manufacturers with isolated catalogs.

Logins:
  admin   / admin123     (super admin - creates manufacturer accounts)
  surya   / surya123     (Surya Textiles)
  heritage/ heritage123  (Heritage Weaves)

Run:  .venv\\Scripts\\python seed.py   (wipes qr_api.db)
"""

import random
from datetime import date, datetime, timedelta

from app.auth import hash_password
from app.database import DB_PATH, get_db, init_db
from app.geo import coords_for
from app.qr_service import new_manual_code, new_token

random.seed(7)

MANUFACTURERS = [
    # username, password, display name, is_admin
    ("admin", "admin123", "VastraApp Super Admin", 1),
    ("surya", "surya123", "Surya Textiles", 0),
    ("heritage", "heritage123", "Heritage Weaves", 0),
]

# per manufacturer username
PRODUCTS = {
    "surya": [
        ("Cotton Saree Classic", "SUR-CS-01", 50),
        ("Silk Dupatta Premium", "SUR-SD-02", 80),
        ("Banarasi Brocade", "SUR-BB-03", 120),
    ],
    "heritage": [
        ("Linen Kurta Fabric", "HER-LK-01", 40),
        ("Handloom Stole", "HER-HS-02", 30),
        ("Ajrakh Print Saree", "HER-AP-03", 70),
    ],
}

RETAILERS = {
    "surya": [
        ("Ramesh Kumar", "Kumar Sarees", "Jaipur"),
        ("Suresh Shah", "Shah Textiles", "Surat"),
        ("Anita Desai", "Desai Fabrics", "Ahmedabad"),
        ("Vikram Singh", "Singh Cloth House", "Ludhiana"),
        ("Meena Iyer", "Iyer Sarees", "Chennai"),
        ("Deepak Verma", "Verma Cloth Stores", "Delhi"),
        ("Sunita Agarwal", "Agarwal Sarees", "Varanasi"),
        ("Farhan Sheikh", "Sheikh Fabrics", "Mumbai"),
    ],
    "heritage": [
        ("Priya Nair", "Nair Silks", "Kochi"),
        ("Arjun Reddy", "Reddy Textiles", "Hyderabad"),
        ("Rahul Bose", "Bose Bastralaya", "Kolkata"),
        ("Kavita Joshi", "Joshi Vastra Bhandar", "Pune"),
        ("Imran Khan", "Khan Fabrics", "Lucknow"),
        ("Lakshmi Rao", "Rao Handlooms", "Bengaluru"),
        ("Mohan Patel", "Patel Textiles", "Indore"),
    ],
}

today = date.today()

SCHEMES = {
    "surya": [
        ("Summer Holiday Offer", "Extra 25 points on every box all summer.",
         -10, +20, 25, []),
        ("Banarasi Festive Push", "60 bonus points per brocade box before "
         "the wedding season.", -5, +15, 60, [2]),
        ("Monsoon Kickoff", "Bonus on sarees when the rains start.",
         +25, +55, 30, [0]),
        ("Republic Day Special", "Flat 20 bonus on all products.",
         -140, -110, 20, []),
    ],
    "heritage": [
        ("Ajrakh Launch Week", "Introductory bonus on the new Ajrakh line.",
         -3, +10, 35, [2]),
        ("Handloom Day Promo", "Celebrate handloom day with stole bonuses.",
         +30, +40, 15, [1]),
        ("New Year Bonanza", "Started the year with bonuses on everything.",
         -160, -150, 40, []),
    ],
}


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    with get_db() as db:
        manuf_ids = {}
        for username, password, display, is_admin in MANUFACTURERS:
            cur = db.execute(
                """INSERT INTO manufacturers
                   (username, password_hash, display_name, is_admin)
                   VALUES (?, ?, ?, ?)""",
                (username, hash_password(password), display, is_admin),
            )
            manuf_ids[username] = cur.lastrowid

        for brand in ("surya", "heritage"):
            mid = manuf_ids[brand]

            product_ids = []
            for name, sku, pts in PRODUCTS[brand]:
                cur = db.execute(
                    """INSERT INTO products
                       (manufacturer_id, name, sku, loyalty_points)
                       VALUES (?, ?, ?, ?)""",
                    (mid, name, sku, pts),
                )
                product_ids.append(cur.lastrowid)

            retailer_rows = []
            for name, shop, city in RETAILERS[brand]:
                lat, lng = coords_for(city)
                cur = db.execute(
                    """INSERT INTO retailers
                       (manufacturer_id, name, shop_name, region, phone, lat, lng)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (mid, name, shop, city,
                     f"98{random.randint(10000000, 99999999)}", lat, lng),
                )
                retailer_rows.append((cur.lastrowid, city))

            scheme_rows = []
            for name, desc, s_off, e_off, bonus, prod_idx in SCHEMES[brand]:
                start = today + timedelta(days=s_off)
                end = today + timedelta(days=e_off)
                cur = db.execute(
                    """INSERT INTO schemes
                       (manufacturer_id, name, description, start_date,
                        end_date, bonus_points)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (mid, name, desc, start.isoformat(), end.isoformat(),
                     bonus),
                )
                covered = [product_ids[i] for i in prod_idx]
                db.executemany(
                    "INSERT INTO scheme_products (scheme_id, product_id)"
                    " VALUES (?, ?)",
                    [(cur.lastrowid, pid) for pid in covered],
                )
                scheme_rows.append(
                    (cur.lastrowid, start, end, bonus,
                     covered or product_ids))

            batches = {}
            for pid in product_ids:
                pts = db.execute(
                    "SELECT loyalty_points FROM products WHERE id = ?",
                    (pid,),
                ).fetchone()["loyalty_points"]
                cur = db.execute(
                    """INSERT INTO qr_batches
                       (product_id, quantity, points_per_code, status)
                       VALUES (?, 400, ?, 'saved')""",
                    (pid, pts),
                )
                batches[pid] = (cur.lastrowid, pts)

            n_scans = 220 if brand == "surya" else 150
            for _ in range(n_scans):
                pid = random.choice(product_ids)
                batch_id, base = batches[pid]
                rid, city = random.choice(retailer_rows)
                scanned = datetime.now() - timedelta(
                    days=random.uniform(0, 180), hours=random.uniform(0, 12))
                scan_day = scanned.date()

                bonus, scheme_id = 0, None
                for s_id, s_start, s_end, s_bonus, s_products in scheme_rows:
                    if s_start <= scan_day <= s_end and pid in s_products:
                        if s_bonus > bonus:
                            bonus, scheme_id = s_bonus, s_id

                token, manual = new_token(), new_manual_code()
                ts = scanned.strftime("%Y-%m-%d %H:%M:%S")
                db.execute(
                    """INSERT INTO qr_codes
                       (token, manual_code, batch_id, redeemed_at, redeemed_by)
                       VALUES (?, ?, ?, ?, ?)""",
                    (token, manual, batch_id, ts, rid),
                )
                db.execute(
                    """INSERT INTO points_ledger
                       (manufacturer_id, retailer_id, token, product_id,
                        points, base_points, bonus_points, scheme_id, region,
                        scanned_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (mid, rid, token, pid, base + bonus, base, bonus,
                     scheme_id, city, ts),
                )

        n = db.execute(
            "SELECT COUNT(*) AS n FROM points_ledger").fetchone()["n"]
    print(f"Seeded 2 manufacturers + super admin, {n} scans -> {DB_PATH}")
    print("Logins: admin/admin123, surya/surya123, heritage/heritage123")


if __name__ == "__main__":
    main()

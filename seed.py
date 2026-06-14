"""Demo data: super admin + two manufacturers with isolated catalogs.

Logins:
  admin   / admin123     (super admin - creates manufacturer accounts)
  surya   / surya123     (Surya Textiles)
  heritage/ heritage123  (Heritage Weaves)

Run:  .venv\\Scripts\\python seed.py
Wipes and refills the configured database (SQLite locally, or the Postgres
in DATABASE_URL). Run once against Neon, then the data persists.
"""

import random
from datetime import date, datetime, timedelta

from app.auth import hash_password
from app.database import get_db, reset_db
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

def _img(name: str) -> str:
    """Placeholder product image in the panel's colours. Manufacturers
    replace these with real product photo URLs when the program goes live."""
    from urllib.parse import quote_plus
    return f"https://placehold.co/400x400/f6f1e6/2b3468?text={quote_plus(name)}"


# Reward catalog (name, description, points_cost), cheapest first. Same list
# for every demo manufacturer; real catalogs are entered in the Gifts tab.
CATALOG = [
    ("Comforter", "Double 90\"x100\"", 1499),
    ("Earbuds", "Boat / Similar Brands", 2199),
    ("Trolley Suitcase", "American Tourister / Similar Brand", 3599),
    ("Smart Watch", "Fastrack / Boat / Similar Brand", 4399),
    ("Mixer Blender", "Boss / Sujata / Similar Brand", 6399),
    ("Desk Jet Printer", "HP / Canon / Epson / Similar Brand", 9999),
    ("Microwave", "LG / Bajaj / Similar Brand", 12999),
    ("Mixer Grinder", "Boss / Sujata / Similar Brand", 14999),
    ("Water Dispenser", "Voltas / Bluestar / Similar Brand", 15999),
    ("Smart Phone", "MI / Realme / Vivo / Similar Brand", 19999),
    ("Silver Biscuit", "150 Grams", 25999),
    ("RO Water Purifier", "Kent / Eureka Forbes / Similar Brand", 29999),
    ("LED TV (32 Inch)", "Samsung / Mi / Similar Brand", 32999),
    ("Washing Machine", "LG / Whirlpool / Similar Brand", 39999),
    ("Refrigerator", "Whirlpool / Similar Brand", 49999),
    ("Laptop", "12th Generation with Windows", 59999),
    ("AC (1.5 Ton)", "Voltas / Similar Brand", 81999),
    ("LED TV (55 Inch)", "Samsung / Mi / Similar Brand", 84999),
    ("Thailand Trip (Bangkok)",
     "1 Pax | 3N-4D | Ex. Ahmedabad, Delhi, Mumbai & Kolkata", 99000),
    ("iPhone 15", "128 GB", 124999),
    ("Scooty", "Activa / Jupiter Ex-Showroom", 169999),
    ("Honda SP 125 Bike", "Ex-Showroom", 179999),
]

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
    reset_db()

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
                # Demo login: first word of the shop name, password +123.
                uname = shop.split()[0].lower()
                cur = db.execute(
                    """INSERT INTO retailers
                       (manufacturer_id, name, shop_name, region, phone,
                        username, password_hash, lat, lng, location_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'city')""",
                    (mid, name, shop, city,
                     f"98{random.randint(10000000, 99999999)}",
                     uname, hash_password(uname + "123"), lat, lng),
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

            # Gift catalog for this manufacturer.
            gift_ids = []
            for gname, gdesc, gcost in CATALOG:
                cur = db.execute(
                    """INSERT INTO gifts
                       (manufacturer_id, name, description, points_cost,
                        image_url)
                       VALUES (?, ?, ?, ?, ?)""",
                    (mid, gname, gdesc, gcost, _img(gname)),
                )
                gift_ids.append((cur.lastrowid, gcost, gname))

            # Demo: top the lead retailer up so the shop shows affordable
            # high-value rewards during the walkthrough.
            rid0 = retailer_rows[0][0]
            db.execute(
                """INSERT INTO points_ledger
                   (manufacturer_id, retailer_id, entry_type, points, note,
                    created_by)
                   VALUES (?, ?, 'adjustment', ?, ?, ?)""",
                (mid, rid0, 150000, "Demo balance top-up", mid),
            )
            # One pending claim awaiting approval (a mid-tier reward).
            demo_gift = next(
                (g for g in gift_ids if g[2] == "LED TV (32 Inch)"),
                gift_ids[0])
            gid, gcost, gname = demo_gift
            debit = db.execute(
                """INSERT INTO points_ledger
                   (manufacturer_id, retailer_id, entry_type, points, note)
                   VALUES (?, ?, 'gift_redeem', ?, ?)""",
                (mid, rid0, -gcost, f"Claim: {gname}"),
            )
            db.execute(
                """INSERT INTO gift_claims
                   (manufacturer_id, retailer_id, gift_id, points_spent,
                    ledger_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (mid, rid0, gid, gcost, debit.lastrowid),
            )

        n = db.execute(
            "SELECT COUNT(*) AS n FROM points_ledger").fetchone()["n"]
    from app.database import IS_PG
    target = "Postgres (DATABASE_URL)" if IS_PG else "SQLite (qr_api.db)"
    print(f"Seeded 2 manufacturers + super admin, {n} scans -> {target}")
    print("Manufacturer logins: admin/admin123, surya/surya123, "
          "heritage/heritage123")
    print("Sample retailer logins (YourApp /web): kumar/kumar123 (Surya), "
          "nair/nair123 (Heritage)")


if __name__ == "__main__":
    main()

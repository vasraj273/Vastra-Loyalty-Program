"""Loyalty QR API — multi-manufacturer backend for Vastra (generate) and
YourApp (scan) plus the manufacturer admin panel.

Roles:
- Super admin (is_admin=1): creates manufacturer accounts. Owns no data.
- Manufacturer: products, retailers, schemes, batches, claims — all scoped
  to the logged-in account.
- Retailer side (/scan, /public/*): open for the webview demo; in production
  YourApp's session must supply the retailer identity.

Webview pages for the demo are served at /web/generate and /web/scan; the
built React panel (panel/dist) is served at /panel when present.
"""

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import (current_admin, current_manufacturer, current_retailer,
                   current_user, hash_password, issue_retailer_token,
                   issue_token, verify_password)
from .database import get_db, init_db, migrate
from .geo import coords_for, known_places, nearest_city
from .pdf_service import build_pdf
from .qr_service import (new_manual_code, new_reference, new_token,
                         payload_for, render_png)

WEB_DIR = Path(__file__).resolve().parent / "web"
PANEL_DIST = Path(__file__).resolve().parent.parent / "panel" / "dist"


def _backfill_coords() -> None:
    """Resolve coordinates for retailers whose region wasn't in the lookup
    when they were added (e.g. state names supported later)."""
    with get_db() as db:
        rows = db.execute(
            "SELECT id, region FROM retailers WHERE lat IS NULL"
        ).fetchall()
        for r in rows:
            coords = coords_for(r["region"])
            if coords:
                db.execute(
                    """UPDATE retailers SET lat = ?, lng = ?,
                       location_source = 'city' WHERE id = ?""",
                    (coords[0], coords[1], r["id"]),
                )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate()
    _backfill_coords()
    yield


app = FastAPI(title="Loyalty QR API", version="4.0.0", lifespan=lifespan)

# Panel dev server. Same-origin in production, so this is dev-only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- schemas ----------

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ManufacturerIn(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=100)
    loyalty_points: int = Field(ge=0, default=0)


class RetailerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    shop_name: str = Field(min_length=1, max_length=200)
    # Optional: when left blank, the city is inferred from the retailer's
    # first scan location (reverse-geocoded to the nearest known city).
    region: str = Field(default="", max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    # Manual override; when omitted, resolved from region city name
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class SchemeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    start_date: date
    end_date: date
    bonus_points: int = Field(ge=1)
    product_ids: list[int] = Field(
        default_factory=list,
        description="Products covered; empty list = all products",
    )


class GenerateIn(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=10_000)
    points_per_code: int | None = Field(
        default=None, ge=0,
        description="Override product's loyalty_points for this batch",
    )
    items_per_box: int | None = Field(
        default=None, ge=2, le=1000,
        description="If set, group children into box (parent) QR codes; "
                    "scanning one box registers all its items at once",
    )


class ScanIn(BaseModel):
    code: str = Field(
        min_length=1, max_length=64,
        description="QR token or 6-char manual code (dashes/spaces ok)",
    )
    # Where this scan happened. Captured once per webview session on the
    # client and sent with every scan; null when location was denied.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class GiftClaimIn(BaseModel):
    gift_id: int


# ---------- auth ----------

@app.post("/auth/login")
def login(body: LoginIn):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM manufacturers WHERE username = ?",
            (body.username.strip().lower(),),
        ).fetchone()
        if not row or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "Invalid username or password")
        token = issue_token(db, row["id"])
    return {
        "token": token,
        "display_name": row["display_name"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
    }


@app.post("/auth/logout")
def logout(request: Request, user: dict = Depends(current_user)):
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    with get_db() as db:
        if token:
            db.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
    return {"ok": True}


# ---------- retailer auth (YourApp side) ----------

@app.post("/auth/retailer/login")
def retailer_login(body: LoginIn):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM retailers WHERE username = ?",
            (body.username.strip().lower(),),
        ).fetchone()
        if (not row or not row["password_hash"]
                or not verify_password(body.password, row["password_hash"])):
            raise HTTPException(401, "Invalid username or password")
        token = issue_retailer_token(db, row["id"])
        manufacturer = db.execute(
            "SELECT display_name FROM manufacturers WHERE id = ?",
            (row["manufacturer_id"],),
        ).fetchone()
    return {
        "token": token,
        "retailer_id": row["id"],
        "shop_name": row["shop_name"],
        "name": row["name"],
        "region": row["region"],
        "manufacturer": manufacturer["display_name"] if manufacturer else None,
    }


@app.post("/auth/retailer/logout")
def retailer_logout(request: Request,
                    retailer: dict = Depends(current_retailer)):
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    with get_db() as db:
        if token:
            db.execute(
                "DELETE FROM retailer_tokens WHERE token = ?", (token,))
    return {"ok": True}


@app.get("/retailer/me")
def retailer_me(retailer: dict = Depends(current_retailer)):
    with get_db() as db:
        balance = _balance(db, retailer["id"])
        manufacturer = db.execute(
            "SELECT display_name FROM manufacturers WHERE id = ?",
            (retailer["manufacturer_id"],),
        ).fetchone()
    return {
        "retailer_id": retailer["id"],
        "shop_name": retailer["shop_name"],
        "name": retailer["name"],
        "region": retailer["region"],
        "manufacturer": manufacturer["display_name"] if manufacturer else None,
        "location_source": retailer["location_source"],
        "balance": balance,
    }


@app.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return user


# ---------- super admin: manufacturer accounts ----------

@app.post("/admin/manufacturers", status_code=201)
def create_manufacturer(body: ManufacturerIn,
                        admin: dict = Depends(current_admin)):
    with get_db() as db:
        try:
            cur = db.execute(
                """INSERT INTO manufacturers
                   (username, password_hash, display_name)
                   VALUES (?, ?, ?)""",
                (body.username.strip().lower(), hash_password(body.password),
                 body.display_name),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, "Username already taken")
            raise
        row = db.execute(
            """SELECT id, username, display_name, created_at
               FROM manufacturers WHERE id = ?""",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


@app.get("/admin/manufacturers")
def list_manufacturers(admin: dict = Depends(current_admin)):
    with get_db() as db:
        rows = db.execute(
            """SELECT m.id, m.username, m.display_name, m.created_at,
                      (SELECT COUNT(*) FROM products p
                       WHERE p.manufacturer_id = m.id) AS products,
                      (SELECT COUNT(*) FROM retailers r
                       WHERE r.manufacturer_id = m.id) AS retailers,
                      (SELECT COUNT(*) FROM points_ledger l
                       WHERE l.manufacturer_id = m.id) AS scans
               FROM manufacturers m WHERE m.is_admin = 0 ORDER BY m.id"""
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- products (manufacturer-scoped) ----------

@app.post("/products", status_code=201)
def create_product(body: ProductIn, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        try:
            cur = db.execute(
                """INSERT INTO products (manufacturer_id, name, sku, loyalty_points)
                   VALUES (?, ?, ?, ?)""",
                (user["id"], body.name, body.sku, body.loyalty_points),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, f"SKU '{body.sku}' already exists")
            raise
        row = db.execute(
            "SELECT * FROM products WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


@app.get("/products")
def list_products(user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        rows = db.execute(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM points_ledger l
                       WHERE l.product_id = p.id) AS scans
               FROM products p WHERE p.manufacturer_id = ? ORDER BY p.id""",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    loyalty_points: int | None = Field(default=None, ge=0)


@app.patch("/products/{product_id}")
def update_product(product_id: int, body: ProductUpdate,
                   user: dict = Depends(current_manufacturer)):
    """Demo-only product management; live products will sync from the
    Vastra ERP. Point changes affect future batches only — already
    generated batches keep their frozen points_per_code."""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(422, "Nothing to update")
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM products WHERE id = ? AND manufacturer_id = ?",
            (product_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Product not found")
        sets = ", ".join(f"{k} = ?" for k in fields)
        try:
            db.execute(
                f"UPDATE products SET {sets} WHERE id = ?",
                [*fields.values(), product_id],
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, "SKU already exists")
            raise
        out = db.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    return dict(out)


@app.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int,
                   user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM products WHERE id = ? AND manufacturer_id = ?",
            (product_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Product not found")
        scans = db.execute(
            "SELECT COUNT(*) AS n FROM points_ledger WHERE product_id = ?",
            (product_id,),
        ).fetchone()["n"]
        if scans:
            raise HTTPException(
                409, "Product has redeemed scans; cannot delete")
        batches = db.execute(
            "SELECT COUNT(*) AS n FROM qr_batches WHERE product_id = ?",
            (product_id,),
        ).fetchone()["n"]
        if batches:
            raise HTTPException(
                409, "Product has QR batches (possibly printed); "
                     "discard its batches first")
        db.execute(
            "DELETE FROM scheme_products WHERE product_id = ?", (product_id,))
        db.execute("DELETE FROM products WHERE id = ?", (product_id,))


# ---------- retailers (manufacturer-scoped) ----------

@app.post("/retailers", status_code=201)
def create_retailer(body: RetailerIn, user: dict = Depends(current_manufacturer)):
    region = (body.region or "").strip()
    lat, lng = body.lat, body.lng
    source = "gps" if (lat is not None and lng is not None) else None
    if (lat is None or lng is None) and region:
        coords = coords_for(region)
        if coords:
            lat, lng = coords
            source = "city"
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO retailers
               (manufacturer_id, name, shop_name, region, phone, lat, lng,
                location_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], body.name, body.shop_name, region, body.phone,
             lat, lng, source),
        )
        rid = cur.lastrowid
        # Auto-create a retailer login so the shop can sign in to YourApp
        # immediately. Username = first word of the shop name (alphanumerics,
        # lowercased); password = <username>123 — the same convention seed.py
        # and backfill_retailer_logins.py use. A clash gets the id appended so
        # the UNIQUE username constraint always holds.
        first = (body.shop_name.split() or ["shop"])[0].lower()
        base = "".join(ch for ch in first if ch.isalnum()) or "shop"
        username = base
        if db.execute("SELECT 1 FROM retailers WHERE username = ?",
                      (username,)).fetchone():
            username = f"{base}{rid}"
        password = f"{username}123"
        db.execute(
            "UPDATE retailers SET username = ?, password_hash = ? WHERE id = ?",
            (username, hash_password(password), rid),
        )
        row = db.execute(
            "SELECT * FROM retailers WHERE id = ?", (rid,)
        ).fetchone()
    out = _clean_retailer(row)
    # Plaintext password is returned only here, at creation, so the panel can
    # show the manufacturer the credentials to hand to the retailer.
    out["login_username"] = username
    out["login_password"] = password
    return out


def _clean_retailer(row) -> dict:
    """Drop the password hash before returning a retailer to the panel."""
    d = dict(row)
    d.pop("password_hash", None)
    d["has_login"] = bool(d.get("username"))
    return d


@app.get("/retailers")
def list_retailers(user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        rows = db.execute(
            """SELECT r.*,
                      (SELECT COUNT(*) FROM points_ledger l
                       WHERE l.retailer_id = r.id AND l.entry_type = 'scan')
                          AS scans,
                      (SELECT COALESCE(SUM(points), 0) FROM points_ledger l
                       WHERE l.retailer_id = r.id) AS points
               FROM retailers r WHERE r.manufacturer_id = ? ORDER BY r.id""",
            (user["id"],),
        ).fetchall()
    return [_clean_retailer(r) for r in rows]


class RetailerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    shop_name: str | None = Field(default=None, min_length=1, max_length=200)
    region: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)


@app.patch("/retailers/{retailer_id}")
def update_retailer(retailer_id: int, body: RetailerUpdate,
                    user: dict = Depends(current_manufacturer)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(422, "Nothing to update")
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM retailers WHERE id = ? AND manufacturer_id = ?",
            (retailer_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Retailer not found")
        # Region change re-resolves the map position unless an exact GPS
        # location is already locked.
        if ("region" in fields and fields["region"] != row["region"]
                and row["location_source"] != "gps"):
            coords = coords_for(fields["region"])
            fields["lat"], fields["lng"] = coords if coords else (None, None)
            fields["location_source"] = "city" if coords else None
        sets = ", ".join(f"{k} = ?" for k in fields)
        db.execute(
            f"UPDATE retailers SET {sets} WHERE id = ?",
            [*fields.values(), retailer_id],
        )
        out = db.execute(
            "SELECT * FROM retailers WHERE id = ?", (retailer_id,)
        ).fetchone()
    return _clean_retailer(out)


@app.delete("/retailers/{retailer_id}", status_code=204)
def delete_retailer(retailer_id: int,
                    user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM retailers WHERE id = ? AND manufacturer_id = ?",
            (retailer_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Retailer not found")
        scans = db.execute(
            "SELECT COUNT(*) AS n FROM points_ledger WHERE retailer_id = ?",
            (retailer_id,),
        ).fetchone()["n"]
        if scans:
            raise HTTPException(
                409, "Retailer has scan history; cannot delete "
                     "(claims would lose their owner)")
        db.execute("DELETE FROM retailers WHERE id = ?", (retailer_id,))


def _balance(db, retailer_id: int) -> int:
    return db.execute(
        "SELECT COALESCE(SUM(points), 0) AS total FROM points_ledger"
        " WHERE retailer_id = ?",
        (retailer_id,),
    ).fetchone()["total"]


class AdjustIn(BaseModel):
    points: int = Field(description="Positive to add, negative to remove")
    note: str = Field(min_length=1, max_length=300)


@app.post("/retailers/{retailer_id}/adjust")
def adjust_points(retailer_id: int, body: AdjustIn,
                  user: dict = Depends(current_manufacturer)):
    """Manual correction by the manufacturer. Cannot push a wallet below 0."""
    if body.points == 0:
        raise HTTPException(422, "points must be non-zero")
    with get_db() as db:
        r = db.execute(
            "SELECT id FROM retailers WHERE id = ? AND manufacturer_id = ?",
            (retailer_id, user["id"]),
        ).fetchone()
        if not r:
            raise HTTPException(404, "Retailer not found")
        if _balance(db, retailer_id) + body.points < 0:
            raise HTTPException(409, "Adjustment would make the wallet negative")
        db.execute(
            """INSERT INTO points_ledger
               (manufacturer_id, retailer_id, entry_type, points, note,
                created_by)
               VALUES (?, ?, 'adjustment', ?, ?, ?)""",
            (user["id"], retailer_id, body.points, body.note, user["id"]),
        )
        return {"retailer_id": retailer_id, "balance": _balance(db, retailer_id)}


class TransferIn(BaseModel):
    from_retailer_id: int
    to_retailer_id: int
    points: int = Field(gt=0)
    note: str = Field(min_length=1, max_length=300)


@app.post("/retailers/transfer")
def transfer_points(body: TransferIn,
                    user: dict = Depends(current_manufacturer)):
    """Move points between two of the manufacturer's retailers (fixes a scan
    credited to the wrong shop)."""
    if body.from_retailer_id == body.to_retailer_id:
        raise HTTPException(422, "Cannot transfer to the same retailer")
    with get_db() as db:
        rows = db.execute(
            "SELECT id FROM retailers WHERE id IN (?, ?) AND manufacturer_id = ?",
            (body.from_retailer_id, body.to_retailer_id, user["id"]),
        ).fetchall()
        if len(rows) != 2:
            raise HTTPException(404, "Both retailers must belong to you")
        if _balance(db, body.from_retailer_id) < body.points:
            raise HTTPException(409, "Sender has insufficient points")
        db.execute(
            """INSERT INTO points_ledger
               (manufacturer_id, retailer_id, entry_type, points,
                counterparty_retailer_id, note, created_by)
               VALUES (?, ?, 'transfer', ?, ?, ?, ?)""",
            (user["id"], body.from_retailer_id, -body.points,
             body.to_retailer_id, body.note, user["id"]),
        )
        db.execute(
            """INSERT INTO points_ledger
               (manufacturer_id, retailer_id, entry_type, points,
                counterparty_retailer_id, note, created_by)
               VALUES (?, ?, 'transfer', ?, ?, ?, ?)""",
            (user["id"], body.to_retailer_id, body.points,
             body.from_retailer_id, body.note, user["id"]),
        )
        return {
            "from": {"id": body.from_retailer_id,
                     "balance": _balance(db, body.from_retailer_id)},
            "to": {"id": body.to_retailer_id,
                   "balance": _balance(db, body.to_retailer_id)},
        }


@app.get("/retailer/wallet")
def retailer_wallet(retailer: dict = Depends(current_retailer)):
    """The logged-in retailer's balance and transaction history."""
    rid = retailer["id"]
    with get_db() as db:
        balance = _balance(db, rid)
        history = db.execute(
            """SELECT l.points, l.base_points, l.bonus_points, l.scanned_at,
                      l.entry_type, l.note,
                      p.name AS product_name, p.sku, s.name AS scheme_name
               FROM points_ledger l
               LEFT JOIN products p ON p.id = l.product_id
               LEFT JOIN schemes s ON s.id = l.scheme_id
               WHERE l.retailer_id = ? ORDER BY l.scanned_at DESC LIMIT 100""",
            (rid,),
        ).fetchall()
    return {
        "retailer_id": rid,
        "shop_name": retailer["shop_name"],
        "region": retailer["region"],
        "balance": balance,
        "history": [dict(h) for h in history],
    }


@app.get("/public/cities")
def public_cities():
    """Known place names for the add-customer autocomplete."""
    return known_places()


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@app.post("/retailer/location")
def set_retailer_location(body: LocationIn,
                          retailer: dict = Depends(current_retailer)):
    """First scan with location permission pins the shop exactly. Once a GPS
    location is locked it never changes (and the app never asks again). If the
    retailer was registered without a city, the region is inferred here from
    the first scan location (nearest known city)."""
    rid = retailer["id"]
    with get_db() as db:
        if retailer["location_source"] == "gps":
            return {"updated": False, "reason": "GPS location already locked"}
        region = (retailer["region"] or "").strip()
        backfilled = None
        if not region:
            backfilled = nearest_city(body.lat, body.lng)
            db.execute(
                """UPDATE retailers SET lat = ?, lng = ?,
                       location_source = 'gps', region = ? WHERE id = ?""",
                (body.lat, body.lng, backfilled or "", rid),
            )
        else:
            db.execute(
                """UPDATE retailers SET lat = ?, lng = ?,
                       location_source = 'gps' WHERE id = ?""",
                (body.lat, body.lng, rid),
            )
    return {"updated": True, "region": backfilled}


# ---------- QR generation (manufacturer-scoped) ----------

@app.post("/qr/generate", status_code=201)
def generate_qr_batch(body: GenerateIn,
                      user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        product = db.execute(
            "SELECT * FROM products WHERE id = ? AND manufacturer_id = ?",
            (body.product_id, user["id"]),
        ).fetchone()
        if not product:
            raise HTTPException(404, "Product not found")

        points = (body.points_per_code if body.points_per_code is not None
                  else product["loyalty_points"])
        cur = db.execute(
            """INSERT INTO qr_batches (product_id, quantity, points_per_code)
               VALUES (?, ?, ?)""",
            (body.product_id, body.quantity, points),
        )
        batch_id = cur.lastrowid

        existing = {
            r["manual_code"]
            for r in db.execute("SELECT manual_code FROM qr_codes")
        }

        def fresh_manual() -> str:
            m = new_manual_code()
            while m in existing:
                m = new_manual_code()
            existing.add(m)
            return m

        # Child codes (one per item).
        children = [(new_token(), fresh_manual()) for _ in range(body.quantity)]

        # Optional box (parent) codes: each parent links a run of children.
        parents = []  # (token, manual, [child_tokens])
        if body.items_per_box:
            for i in range(0, body.quantity, body.items_per_box):
                group = children[i:i + body.items_per_box]
                parents.append(
                    (new_token(), fresh_manual(), [t for t, _ in group]))

        child_to_parent = {}
        for p_token, _, child_tokens in parents:
            for ct in child_tokens:
                child_to_parent[ct] = p_token

        db.executemany(
            """INSERT INTO qr_codes
               (token, manual_code, batch_id, is_parent, parent_token)
               VALUES (?, ?, ?, 0, ?)""",
            [(t, m, batch_id, child_to_parent.get(t)) for t, m in children],
        )
        if parents:
            db.executemany(
                """INSERT INTO qr_codes
                   (token, manual_code, batch_id, is_parent, parent_token)
                   VALUES (?, ?, ?, 1, NULL)""",
                [(t, m, batch_id) for t, m, _ in parents],
            )

    return {
        "batch_id": batch_id,
        "product_id": body.product_id,
        "product_name": product["name"],
        "quantity": body.quantity,
        "points_per_code": points,
        "items_per_box": body.items_per_box,
        "boxes": len(parents),
        "status": "pending",
        "codes": [
            {"token": t, "manual_code": m, "payload": payload_for(t)}
            for t, m in children
        ],
        "boxes_codes": [
            {"token": t, "manual_code": m, "payload": payload_for(t),
             "items": len(ch)}
            for t, m, ch in parents
        ],
        "actions": {
            "save": f"/qr/batches/{batch_id}/save",
            "print": f"/qr/batches/{batch_id}/print",
            "discard": f"/qr/batches/{batch_id}",
        },
    }


# ---------- batches (manufacturer-scoped) ----------

def _get_batch(db, batch_id: int, manufacturer_id: int):
    batch = db.execute(
        """SELECT b.*, p.name AS product_name, p.sku
           FROM qr_batches b JOIN products p ON p.id = b.product_id
           WHERE b.id = ? AND p.manufacturer_id = ?""",
        (batch_id, manufacturer_id),
    ).fetchone()
    if not batch:
        raise HTTPException(404, "Batch not found")
    return batch


@app.post("/qr/batches/{batch_id}/save")
def save_batch(batch_id: int, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        _get_batch(db, batch_id, user["id"])
        db.execute(
            "UPDATE qr_batches SET status = 'saved' WHERE id = ?", (batch_id,)
        )
    return {"batch_id": batch_id, "status": "saved"}


@app.get("/qr/batches")
def list_batches(status: str | None = Query(None, pattern="^(pending|saved)$"),
                 user: dict = Depends(current_manufacturer)):
    sql = """SELECT b.*, p.name AS product_name, p.sku
             FROM qr_batches b JOIN products p ON p.id = b.product_id
             WHERE p.manufacturer_id = ?"""
    args: list = [user["id"]]
    if status:
        sql += " AND b.status = ?"
        args.append(status)
    sql += " ORDER BY b.id DESC"
    with get_db() as db:
        rows = db.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@app.get("/qr/batches/{batch_id}")
def get_batch(batch_id: int, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        batch = _get_batch(db, batch_id, user["id"])
        codes = db.execute(
            """SELECT token, manual_code, redeemed_at, redeemed_by
               FROM qr_codes WHERE batch_id = ?""",
            (batch_id,),
        ).fetchall()
    out = dict(batch)
    out["codes"] = [dict(c) for c in codes]
    return out


@app.get("/qr/batches/{batch_id}/print")
def print_batch(batch_id: int, user: dict = Depends(current_manufacturer)):
    """Printable A4 PDF. Accepts ?token= auth so it can open in a new tab."""
    with get_db() as db:
        batch = _get_batch(db, batch_id, user["id"])
        # Children first, then box (parent) codes; each parent carries its
        # item count so the sticker can be labelled.
        child_rows = db.execute(
            """SELECT token, manual_code FROM qr_codes
               WHERE batch_id = ? AND is_parent = 0 ORDER BY token""",
            (batch_id,),
        ).fetchall()
        codes = [(r["token"], r["manual_code"], 0) for r in child_rows]
        parent_rows = db.execute(
            """SELECT token, manual_code,
                      (SELECT COUNT(*) FROM qr_codes ch
                       WHERE ch.parent_token = c.token) AS items
               FROM qr_codes c
               WHERE c.batch_id = ? AND c.is_parent = 1 ORDER BY c.token""",
            (batch_id,),
        ).fetchall()
        codes += [(r["token"], r["manual_code"], r["items"])
                  for r in parent_rows]
    pdf = build_pdf(batch["product_name"], batch["sku"], codes)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'inline; filename="loyalty-qr-batch-{batch_id}.pdf"'
        },
    )


@app.delete("/qr/batches/{batch_id}", status_code=204)
def discard_batch(batch_id: int, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        _get_batch(db, batch_id, user["id"])
        db.execute("DELETE FROM qr_codes WHERE batch_id = ?", (batch_id,))
        db.execute("DELETE FROM qr_batches WHERE id = ?", (batch_id,))


# ---------- single code image (open) ----------

@app.get("/qr/codes/{token}/image")
def code_image(token: str):
    with get_db() as db:
        row = db.execute(
            "SELECT token FROM qr_codes WHERE token = ?", (token,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Code not found")
    return Response(content=render_png(token), media_type="image/png")


# ---------- scan & redeem (retailer side, authenticated) ----------

@app.post("/scan")
def scan(body: ScanIn, retailer: dict = Depends(current_retailer)):
    """Redeem a code by QR token or 6-char manual code. Points always go to
    the logged-in retailer, so a code can't be credited to another account.
    Single authority for rewards: base points + best active scheme bonus."""
    rid = retailer["id"]
    code = body.code.strip().replace("-", "").replace(" ", "").upper()
    with get_db() as db:
        row = db.execute(
            """SELECT c.token, c.redeemed_at, c.is_parent, b.points_per_code,
                      p.id AS product_id, p.name AS product_name, p.sku,
                      p.manufacturer_id
               FROM qr_codes c
               JOIN qr_batches b ON b.id = c.batch_id
               JOIN products p ON p.id = b.product_id
               WHERE c.token = ? OR c.manual_code = ?""",
            (body.code.strip(), code),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Invalid code")
        if retailer["manufacturer_id"] != row["manufacturer_id"]:
            raise HTTPException(
                403, "This code belongs to a different manufacturer")

        # A box (parent) code registers all of its still-unredeemed children;
        # a plain code registers just itself.
        if row["is_parent"]:
            tokens = [
                c["token"] for c in db.execute(
                    """SELECT token FROM qr_codes
                       WHERE parent_token = ? AND redeemed_at IS NULL""",
                    (row["token"],),
                )
            ]
            if not tokens:
                raise HTTPException(409, "Box already redeemed")
        else:
            if row["redeemed_at"]:
                raise HTTPException(409, "Code already redeemed")
            tokens = [row["token"]]

        # Base points always apply; the most generous active scheme of this
        # manufacturer covering the product adds its bonus (no stacking). All
        # children of a box share one product, so the per-item value is equal.
        scheme = db.execute(
            """SELECT s.id, s.name, s.bonus_points FROM schemes s
               WHERE s.manufacturer_id = ?
                 AND date('now') BETWEEN s.start_date AND s.end_date
                 AND (NOT EXISTS (SELECT 1 FROM scheme_products sp
                                  WHERE sp.scheme_id = s.id)
                      OR EXISTS (SELECT 1 FROM scheme_products sp
                                 WHERE sp.scheme_id = s.id
                                   AND sp.product_id = ?))
               ORDER BY s.bonus_points DESC LIMIT 1""",
            (row["manufacturer_id"], row["product_id"]),
        ).fetchone()
        base = row["points_per_code"]
        bonus = scheme["bonus_points"] if scheme else 0
        per = base + bonus

        for t in tokens:
            db.execute(
                """UPDATE qr_codes SET redeemed_at = datetime('now'),
                                       redeemed_by = ? WHERE token = ?""",
                (rid, t),
            )
            db.execute(
                """INSERT INTO points_ledger
                   (manufacturer_id, retailer_id, token, product_id, points,
                    base_points, bonus_points, scheme_id, region, lat, lng)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["manufacturer_id"], rid, t,
                 row["product_id"], per, base, bonus,
                 scheme["id"] if scheme else None, retailer["region"],
                 body.lat, body.lng),
            )
        if row["is_parent"]:
            db.execute(
                """UPDATE qr_codes SET redeemed_at = datetime('now'),
                                       redeemed_by = ? WHERE token = ?""",
                (rid, row["token"]),
            )

        count = len(tokens)
        balance = db.execute(
            "SELECT COALESCE(SUM(points), 0) AS total FROM points_ledger"
            " WHERE retailer_id = ?",
            (rid,),
        ).fetchone()["total"]

    return {
        "redeemed": True,
        "is_box": bool(row["is_parent"]),
        "items_registered": count,
        "product": {"id": row["product_id"], "name": row["product_name"],
                    "sku": row["sku"]},
        "points_awarded": per * count,
        "base_points": base * count,
        "bonus_points": bonus * count,
        "scheme": ({"id": scheme["id"], "name": scheme["name"]}
                   if scheme else None),
        "retailer": {"id": rid,
                     "shop_name": retailer["shop_name"],
                     "region": retailer["region"]},
        "new_balance": balance,
    }


# ---------- schemes / campaigns (manufacturer-scoped) ----------

def _scheme_status(start_date: str, end_date: str) -> str:
    today = date.today().isoformat()
    if today < start_date:
        return "upcoming"
    if today > end_date:
        return "previous"
    return "active"


def _scheme_out(db, row) -> dict:
    products = db.execute(
        """SELECT p.id, p.name, p.sku FROM scheme_products sp
           JOIN products p ON p.id = sp.product_id WHERE sp.scheme_id = ?""",
        (row["id"],),
    ).fetchall()
    out = dict(row)
    out["status"] = _scheme_status(row["start_date"], row["end_date"])
    out["products"] = [dict(p) for p in products]  # empty = all products
    out["all_products"] = not products
    return out


@app.post("/schemes", status_code=201)
def create_scheme(body: SchemeIn, user: dict = Depends(current_manufacturer)):
    if body.end_date < body.start_date:
        raise HTTPException(422, "end_date must be on or after start_date")
    with get_db() as db:
        if body.product_ids:
            found = db.execute(
                f"""SELECT COUNT(*) AS n FROM products
                    WHERE manufacturer_id = ?
                      AND id IN ({','.join('?' * len(body.product_ids))})""",
                [user["id"], *body.product_ids],
            ).fetchone()["n"]
            if found != len(set(body.product_ids)):
                raise HTTPException(404, "One or more product_ids not found")
        cur = db.execute(
            """INSERT INTO schemes
               (manufacturer_id, name, description, start_date, end_date,
                bonus_points)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user["id"], body.name, body.description,
             body.start_date.isoformat(), body.end_date.isoformat(),
             body.bonus_points),
        )
        scheme_id = cur.lastrowid
        db.executemany(
            "INSERT INTO scheme_products (scheme_id, product_id) VALUES (?, ?)",
            [(scheme_id, pid) for pid in set(body.product_ids)],
        )
        row = db.execute(
            "SELECT * FROM schemes WHERE id = ?", (scheme_id,)
        ).fetchone()
        return _scheme_out(db, row)


@app.get("/schemes")
def list_schemes(status: str | None = Query(
        None, pattern="^(active|upcoming|previous)$"),
        user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        rows = db.execute(
            """SELECT * FROM schemes WHERE manufacturer_id = ?
               ORDER BY start_date DESC""",
            (user["id"],),
        ).fetchall()
        out = [_scheme_out(db, r) for r in rows]
    if status:
        out = [s for s in out if s["status"] == status]
    return out


@app.delete("/schemes/{scheme_id}", status_code=204)
def delete_scheme(scheme_id: int, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM schemes WHERE id = ? AND manufacturer_id = ?",
            (scheme_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Scheme not found")
        used = db.execute(
            "SELECT COUNT(*) AS n FROM points_ledger WHERE scheme_id = ?",
            (scheme_id,),
        ).fetchone()["n"]
        if used:
            raise HTTPException(
                409, "Scheme has redemptions against it; cannot delete")
        db.execute("DELETE FROM schemes WHERE id = ?", (scheme_id,))


# ---------- claims (manufacturer-scoped) ----------

@app.get("/claims")
def list_claims(
    product_id: int | None = None,
    retailer_id: int | None = None,
    region: str | None = None,
    scheme_id: int | None = None,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(current_manufacturer),
):
    where = " WHERE l.manufacturer_id = ? AND l.entry_type = 'scan'"
    args: list = [user["id"]]
    if product_id is not None:
        where += " AND l.product_id = ?"
        args.append(product_id)
    if retailer_id is not None:
        where += " AND l.retailer_id = ?"
        args.append(retailer_id)
    if region:
        where += " AND l.region = ?"
        args.append(region)
    if scheme_id is not None:
        where += " AND l.scheme_id = ?"
        args.append(scheme_id)
    if date_from:
        where += " AND l.scanned_at >= ?"
        args.append(date_from)
    if date_to:
        where += " AND l.scanned_at <= ?"
        args.append(date_to)

    with get_db() as db:
        total = db.execute(
            f"SELECT COUNT(*) AS n FROM points_ledger l{where}", args
        ).fetchone()["n"]
        rows = db.execute(
            f"""SELECT l.id, l.scanned_at, l.points, l.base_points,
                       l.bonus_points, l.region, l.token,
                       p.id AS product_id, p.name AS product_name, p.sku,
                       r.id AS retailer_id, r.name AS retailer_name,
                       r.shop_name, r.lat, r.lng,
                       s.id AS scheme_id, s.name AS scheme_name
                FROM points_ledger l
                JOIN products p ON p.id = l.product_id
                JOIN retailers r ON r.id = l.retailer_id
                LEFT JOIN schemes s ON s.id = l.scheme_id
                {where} ORDER BY l.scanned_at DESC LIMIT ? OFFSET ?""",
            args + [limit, offset],
        ).fetchall()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "claims": [dict(r) for r in rows],
    }


# ---------- dashboard (manufacturer-scoped) ----------

@app.get("/analytics/dashboard")
def dashboard(user: dict = Depends(current_manufacturer)):
    mid = user["id"]
    with get_db() as db:
        totals = db.execute(
            """SELECT
                 (SELECT COUNT(*) FROM retailers WHERE manufacturer_id = :m)
                     AS retailers,
                 (SELECT COUNT(*) FROM products WHERE manufacturer_id = :m)
                     AS products,
                 (SELECT COUNT(*) FROM points_ledger
                  WHERE manufacturer_id = :m AND entry_type = 'scan')
                     AS scans,
                 (SELECT COALESCE(SUM(points), 0) FROM points_ledger
                  WHERE manufacturer_id = :m AND entry_type = 'scan')
                     AS points_awarded,
                 (SELECT COUNT(*) FROM qr_codes c
                  JOIN qr_batches b ON b.id = c.batch_id
                  JOIN products p ON p.id = b.product_id
                  WHERE p.manufacturer_id = :m) AS codes_issued""",
            {"m": mid},
        ).fetchone()
        by_region = db.execute(
            """SELECT region, COUNT(*) AS scans, SUM(points) AS points
               FROM points_ledger WHERE manufacturer_id = ?
                 AND entry_type = 'scan'
               GROUP BY region ORDER BY scans DESC""",
            (mid,),
        ).fetchall()
        by_product = db.execute(
            """SELECT p.id, p.name, p.sku, COUNT(l.id) AS scans,
                      COALESCE(SUM(l.points), 0) AS points
               FROM products p LEFT JOIN points_ledger l
                 ON l.product_id = p.id AND l.entry_type = 'scan'
               WHERE p.manufacturer_id = ?
               GROUP BY p.id ORDER BY scans DESC""",
            (mid,),
        ).fetchall()
        top_retailers = db.execute(
            """SELECT r.id, r.name, r.shop_name, r.region, COUNT(*) AS scans,
                      SUM(l.points) AS points
               FROM points_ledger l JOIN retailers r ON r.id = l.retailer_id
               WHERE l.manufacturer_id = ? AND l.entry_type = 'scan'
               GROUP BY r.id ORDER BY points DESC LIMIT 10""",
            (mid,),
        ).fetchall()
        # One dot per place a retailer actually scanned: use the per-scan GPS
        # captured at scan time, falling back to the retailer's pinned shop
        # coords for scans recorded without a location. Bucketed in Python by
        # ~110m (3 decimals) so repeated scans at one spot collapse to a single
        # weighted dot (and to keep the SQL backend-portable).
        scan_rows = db.execute(
            """SELECT r.id, r.name, r.shop_name, r.region,
                      COALESCE(l.lat, r.lat) AS lat,
                      COALESCE(l.lng, r.lng) AS lng,
                      l.points AS points, l.scanned_at AS scanned_at
               FROM points_ledger l JOIN retailers r ON r.id = l.retailer_id
               WHERE l.manufacturer_id = ? AND l.entry_type = 'scan'
                 AND COALESCE(l.lat, r.lat) IS NOT NULL
                 AND COALESCE(l.lng, r.lng) IS NOT NULL""",
            (mid,),
        ).fetchall()
    buckets: dict[tuple, dict] = {}
    for s in scan_rows:
        lat, lng = round(s["lat"], 3), round(s["lng"], 3)
        key = (s["id"], lat, lng)
        b = buckets.get(key)
        if b is None:
            b = {"id": s["id"], "name": s["name"], "shop_name": s["shop_name"],
                 "region": s["region"], "lat": lat, "lng": lng,
                 "scans": 0, "points": 0, "last_scan": s["scanned_at"]}
            buckets[key] = b
        b["scans"] += 1
        b["points"] += s["points"] or 0
        if s["scanned_at"] and s["scanned_at"] > (b["last_scan"] or ""):
            b["last_scan"] = s["scanned_at"]
    map_points = list(buckets.values())
    return {
        "totals": dict(totals),
        "by_region": [dict(r) for r in by_region],
        "by_product": [dict(r) for r in by_product],
        "top_retailers": [dict(r) for r in top_retailers],
        "map_points": [dict(r) for r in map_points],
    }


# ---------- gift catalog (manufacturer-scoped) ----------

class GiftIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    points_cost: int = Field(ge=1)
    image_url: str | None = None  # URL or data: URI (uploaded photo)


class GiftUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    points_cost: int | None = Field(default=None, ge=1)
    image_url: str | None = None  # URL or data: URI (uploaded photo)
    active: bool | None = None


@app.post("/gifts", status_code=201)
def create_gift(body: GiftIn, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO gifts
               (manufacturer_id, name, description, points_cost, image_url)
               VALUES (?, ?, ?, ?, ?)""",
            (user["id"], body.name, body.description, body.points_cost,
             body.image_url),
        )
        row = db.execute(
            "SELECT * FROM gifts WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


@app.get("/gifts")
def list_gifts(user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        rows = db.execute(
            """SELECT g.*,
                      (SELECT COUNT(*) FROM gift_claims gc
                       WHERE gc.gift_id = g.id) AS claims
               FROM gifts g WHERE g.manufacturer_id = ? ORDER BY g.id""",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.patch("/gifts/{gift_id}")
def update_gift(gift_id: int, body: GiftUpdate,
                user: dict = Depends(current_manufacturer)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "active" in fields:
        fields["active"] = 1 if fields["active"] else 0
    if not fields:
        raise HTTPException(422, "Nothing to update")
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM gifts WHERE id = ? AND manufacturer_id = ?",
            (gift_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Gift not found")
        sets = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE gifts SET {sets} WHERE id = ?",
                   [*fields.values(), gift_id])
        out = db.execute(
            "SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()
    return dict(out)


@app.delete("/gifts/{gift_id}", status_code=204)
def delete_gift(gift_id: int, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM gifts WHERE id = ? AND manufacturer_id = ?",
            (gift_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Gift not found")
        used = db.execute(
            "SELECT COUNT(*) AS n FROM gift_claims WHERE gift_id = ?",
            (gift_id,),
        ).fetchone()["n"]
        if used:
            raise HTTPException(
                409, "Gift has claims; deactivate it instead of deleting")
        db.execute("DELETE FROM gifts WHERE id = ?", (gift_id,))


# ---------- gift shop + claims (retailer side, authenticated) ----------

@app.get("/retailer/shop")
def retailer_shop(retailer: dict = Depends(current_retailer)):
    """Shop view for the logged-in retailer: wallet balance + the active
    gifts of their manufacturer, flagged affordable or not."""
    rid = retailer["id"]
    with get_db() as db:
        balance = _balance(db, rid)
        gifts = db.execute(
            """SELECT id, name, description, points_cost, image_url
               FROM gifts WHERE manufacturer_id = ? AND active = 1
               ORDER BY points_cost""",
            (retailer["manufacturer_id"],),
        ).fetchall()
    return {
        "retailer_id": rid,
        "shop_name": retailer["shop_name"],
        "balance": balance,
        "gifts": [
            {**dict(g), "affordable": balance >= g["points_cost"]}
            for g in gifts
        ],
    }


@app.post("/retailer/claim", status_code=201)
def claim_gift(body: GiftClaimIn, retailer: dict = Depends(current_retailer)):
    """Logged-in retailer claims a gift. Points are deducted immediately; a
    rejected claim refunds them. The manufacturer fulfils the gift offline."""
    rid = retailer["id"]
    with get_db() as db:
        gift = db.execute(
            "SELECT * FROM gifts WHERE id = ? AND active = 1", (body.gift_id,)
        ).fetchone()
        if not gift:
            raise HTTPException(404, "Gift not available")
        if gift["manufacturer_id"] != retailer["manufacturer_id"]:
            raise HTTPException(403, "Gift belongs to another manufacturer")
        if _balance(db, rid) < gift["points_cost"]:
            raise HTTPException(409, "Not enough points")

        debit = db.execute(
            """INSERT INTO points_ledger
               (manufacturer_id, retailer_id, entry_type, points, note)
               VALUES (?, ?, 'gift_redeem', ?, ?)""",
            (gift["manufacturer_id"], rid, -gift["points_cost"],
             f"Claim: {gift['name']}"),
        )
        existing = {
            r["reference"] for r in db.execute(
                "SELECT reference FROM gift_claims WHERE reference IS NOT NULL")
        }
        reference = new_reference()
        while reference in existing:
            reference = new_reference()
        cur = db.execute(
            """INSERT INTO gift_claims
               (manufacturer_id, retailer_id, gift_id, reference, points_spent,
                ledger_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (gift["manufacturer_id"], rid, body.gift_id, reference,
             gift["points_cost"], debit.lastrowid),
        )
        return {
            "claim_id": cur.lastrowid,
            "reference": reference,
            "gift": gift["name"],
            "points_spent": gift["points_cost"],
            "status": "pending",
            "new_balance": _balance(db, rid),
        }


@app.get("/retailer/claims")
def retailer_claims(retailer: dict = Depends(current_retailer)):
    """The logged-in retailer's gift claim history (order-history style)."""
    with get_db() as db:
        rows = db.execute(
            """SELECT gc.id, gc.reference, gc.points_spent, gc.status,
                      gc.created_at, gc.decided_at,
                      g.name AS gift_name, g.image_url, g.description
               FROM gift_claims gc JOIN gifts g ON g.id = gc.gift_id
               WHERE gc.retailer_id = ? ORDER BY gc.id DESC""",
            (retailer["id"],),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["reference"] = d["reference"] or f"CLM-{d['id']}"
        out.append(d)
    return out


@app.get("/gift-claims")
def list_gift_claims(status: str | None = Query(
        None, pattern="^(pending|approved|rejected)$"),
        user: dict = Depends(current_manufacturer)):
    sql = """SELECT gc.id, gc.reference, gc.points_spent, gc.status,
                    gc.created_at, gc.decided_at, g.name AS gift_name,
                    r.id AS retailer_id, r.shop_name, r.name AS retailer_name,
                    r.region
             FROM gift_claims gc
             JOIN gifts g ON g.id = gc.gift_id
             JOIN retailers r ON r.id = gc.retailer_id
             WHERE gc.manufacturer_id = ?"""
    args: list = [user["id"]]
    if status:
        sql += " AND gc.status = ?"
        args.append(status)
    sql += " ORDER BY gc.id DESC"
    with get_db() as db:
        rows = db.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def _decide_claim(db, claim_id, manufacturer_id):
    claim = db.execute(
        "SELECT * FROM gift_claims WHERE id = ? AND manufacturer_id = ?",
        (claim_id, manufacturer_id),
    ).fetchone()
    if not claim:
        raise HTTPException(404, "Claim not found")
    if claim["status"] != "pending":
        raise HTTPException(409, f"Claim already {claim['status']}")
    return claim


@app.post("/gift-claims/{claim_id}/approve")
def approve_claim(claim_id: int, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        _decide_claim(db, claim_id, user["id"])
        db.execute(
            """UPDATE gift_claims SET status = 'approved',
               decided_at = datetime('now') WHERE id = ?""",
            (claim_id,),
        )
    return {"claim_id": claim_id, "status": "approved"}


@app.post("/gift-claims/{claim_id}/reject")
def reject_claim(claim_id: int, user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        claim = _decide_claim(db, claim_id, user["id"])
        # Refund the points that were deducted at claim time.
        db.execute(
            """INSERT INTO points_ledger
               (manufacturer_id, retailer_id, entry_type, points, note)
               VALUES (?, ?, 'refund', ?, ?)""",
            (user["id"], claim["retailer_id"], claim["points_spent"],
             "Refund: gift claim rejected"),
        )
        db.execute(
            """UPDATE gift_claims SET status = 'rejected',
               decided_at = datetime('now') WHERE id = ?""",
            (claim_id,),
        )
    return {"claim_id": claim_id, "status": "rejected",
            "refunded": claim["points_spent"]}


# ---------- webview pages + built panel ----------

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/panel/")

@app.get("/web", include_in_schema=False)
def web_home():
    return FileResponse(WEB_DIR / "home.html")


@app.get("/web/generate", include_in_schema=False)
def web_generate():
    return FileResponse(WEB_DIR / "generate.html")


@app.get("/web/scan", include_in_schema=False)
@app.get("/web/scan/{token}", include_in_schema=False)
def web_scan(token: str | None = None):
    return FileResponse(WEB_DIR / "scan.html")


@app.get("/web/shop", include_in_schema=False)
def web_shop():
    return FileResponse(WEB_DIR / "shop.html")


@app.get("/web/claims", include_in_schema=False)
def web_claims():
    return FileResponse(WEB_DIR / "claims.html")


if PANEL_DIST.exists():
    app.mount("/panel", StaticFiles(directory=PANEL_DIST, html=True),
              name="panel")

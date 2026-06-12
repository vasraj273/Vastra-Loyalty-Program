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

from .auth import (current_admin, current_manufacturer, current_user,
                   hash_password, issue_token, verify_password)
from .database import get_db, init_db
from .geo import coords_for, known_places
from .pdf_service import build_pdf
from .qr_service import new_manual_code, new_token, payload_for, render_png

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
    region: str = Field(min_length=1, max_length=100)
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


class ScanIn(BaseModel):
    code: str = Field(
        min_length=1, max_length=64,
        description="QR token or 6-char manual code (dashes/spaces ok)",
    )
    retailer_id: int


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
            "SELECT * FROM products WHERE manufacturer_id = ? ORDER BY id",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- retailers (manufacturer-scoped) ----------

@app.post("/retailers", status_code=201)
def create_retailer(body: RetailerIn, user: dict = Depends(current_manufacturer)):
    lat, lng = body.lat, body.lng
    source = "gps" if (lat is not None and lng is not None) else None
    if lat is None or lng is None:
        coords = coords_for(body.region)
        if coords:
            lat, lng = coords
            source = "city"
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO retailers
               (manufacturer_id, name, shop_name, region, phone, lat, lng,
                location_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], body.name, body.shop_name, body.region, body.phone,
             lat, lng, source),
        )
        row = db.execute(
            "SELECT * FROM retailers WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


@app.get("/retailers")
def list_retailers(user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        rows = db.execute(
            """SELECT r.*,
                      (SELECT COUNT(*) FROM points_ledger l
                       WHERE l.retailer_id = r.id) AS scans,
                      (SELECT COALESCE(SUM(points), 0) FROM points_ledger l
                       WHERE l.retailer_id = r.id) AS points
               FROM retailers r WHERE r.manufacturer_id = ? ORDER BY r.id""",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/retailers/{retailer_id}/points")
def retailer_points(retailer_id: int):
    """Open: the retailer side (YourApp webview) reads its own balance."""
    with get_db() as db:
        retailer = db.execute(
            "SELECT * FROM retailers WHERE id = ?", (retailer_id,)
        ).fetchone()
        if not retailer:
            raise HTTPException(404, "Retailer not found")
        balance = db.execute(
            "SELECT COALESCE(SUM(points), 0) AS total FROM points_ledger"
            " WHERE retailer_id = ?",
            (retailer_id,),
        ).fetchone()["total"]
        history = db.execute(
            """SELECT l.points, l.base_points, l.bonus_points, l.scanned_at,
                      p.name AS product_name, p.sku, s.name AS scheme_name
               FROM points_ledger l
               JOIN products p ON p.id = l.product_id
               LEFT JOIN schemes s ON s.id = l.scheme_id
               WHERE l.retailer_id = ? ORDER BY l.scanned_at DESC LIMIT 100""",
            (retailer_id,),
        ).fetchall()
    return {
        "retailer_id": retailer_id,
        "shop_name": retailer["shop_name"],
        "region": retailer["region"],
        "balance": balance,
        "history": [dict(h) for h in history],
    }


@app.get("/public/retailers")
def public_retailers():
    """DEMO ONLY: lets the scan webview pick 'who is scanning'. In production
    the retailer identity comes from YourApp's login session."""
    with get_db() as db:
        rows = db.execute(
            """SELECT r.id, r.shop_name, r.region, r.location_source,
                      m.display_name AS manufacturer
               FROM retailers r
               JOIN manufacturers m ON m.id = r.manufacturer_id
               ORDER BY m.display_name, r.shop_name"""
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/public/cities")
def public_cities():
    """Known place names for the add-customer autocomplete."""
    return known_places()


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@app.post("/public/retailers/{retailer_id}/location")
def set_retailer_location(retailer_id: int, body: LocationIn):
    """First scan with location permission pins the shop exactly. Once a GPS
    location is locked it never changes (and the app never asks again)."""
    with get_db() as db:
        row = db.execute(
            "SELECT id, location_source FROM retailers WHERE id = ?",
            (retailer_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Retailer not found")
        if row["location_source"] == "gps":
            return {"updated": False, "reason": "GPS location already locked"}
        db.execute(
            """UPDATE retailers SET lat = ?, lng = ?, location_source = 'gps'
               WHERE id = ?""",
            (body.lat, body.lng, retailer_id),
        )
    return {"updated": True}


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
        codes = []
        for _ in range(body.quantity):
            manual = new_manual_code()
            while manual in existing:
                manual = new_manual_code()
            existing.add(manual)
            codes.append((new_token(), manual))
        db.executemany(
            "INSERT INTO qr_codes (token, manual_code, batch_id) VALUES (?, ?, ?)",
            [(t, m, batch_id) for t, m in codes],
        )

    return {
        "batch_id": batch_id,
        "product_id": body.product_id,
        "product_name": product["name"],
        "quantity": body.quantity,
        "points_per_code": points,
        "status": "pending",
        "codes": [
            {"token": t, "manual_code": m, "payload": payload_for(t)}
            for t, m in codes
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
        codes = [
            (r["token"], r["manual_code"])
            for r in db.execute(
                "SELECT token, manual_code FROM qr_codes WHERE batch_id = ?",
                (batch_id,),
            )
        ]
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


# ---------- scan & redeem (retailer side, open for demo) ----------

@app.post("/scan")
def scan(body: ScanIn):
    """Redeem a code by QR token or 6-char manual code. Single authority for
    rewards: base points from the batch + best active scheme bonus."""
    code = body.code.strip().replace("-", "").replace(" ", "").upper()
    with get_db() as db:
        retailer = db.execute(
            "SELECT * FROM retailers WHERE id = ?", (body.retailer_id,)
        ).fetchone()
        if not retailer:
            raise HTTPException(404, "Retailer not found")

        row = db.execute(
            """SELECT c.token, c.redeemed_at, b.points_per_code,
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
        if row["redeemed_at"]:
            raise HTTPException(409, "Code already redeemed")
        if retailer["manufacturer_id"] != row["manufacturer_id"]:
            raise HTTPException(
                403, "This code belongs to a different manufacturer")

        # Base points always apply; the most generous active scheme of this
        # manufacturer covering the product adds its bonus (no stacking).
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

        db.execute(
            """UPDATE qr_codes SET redeemed_at = datetime('now'),
                                   redeemed_by = ? WHERE token = ?""",
            (body.retailer_id, row["token"]),
        )
        db.execute(
            """INSERT INTO points_ledger
               (manufacturer_id, retailer_id, token, product_id, points,
                base_points, bonus_points, scheme_id, region)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["manufacturer_id"], body.retailer_id, row["token"],
             row["product_id"], base + bonus, base, bonus,
             scheme["id"] if scheme else None, retailer["region"]),
        )
        balance = db.execute(
            "SELECT COALESCE(SUM(points), 0) AS total FROM points_ledger"
            " WHERE retailer_id = ?",
            (body.retailer_id,),
        ).fetchone()["total"]

    return {
        "redeemed": True,
        "product": {"id": row["product_id"], "name": row["product_name"],
                    "sku": row["sku"]},
        "points_awarded": base + bonus,
        "base_points": base,
        "bonus_points": bonus,
        "scheme": ({"id": scheme["id"], "name": scheme["name"]}
                   if scheme else None),
        "retailer": {"id": body.retailer_id,
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
    where = " WHERE l.manufacturer_id = ?"
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
                 (SELECT COUNT(*) FROM points_ledger WHERE manufacturer_id = :m)
                     AS scans,
                 (SELECT COALESCE(SUM(points), 0) FROM points_ledger
                  WHERE manufacturer_id = :m) AS points_awarded,
                 (SELECT COUNT(*) FROM qr_codes c
                  JOIN qr_batches b ON b.id = c.batch_id
                  JOIN products p ON p.id = b.product_id
                  WHERE p.manufacturer_id = :m) AS codes_issued""",
            {"m": mid},
        ).fetchone()
        by_region = db.execute(
            """SELECT region, COUNT(*) AS scans, SUM(points) AS points
               FROM points_ledger WHERE manufacturer_id = ?
               GROUP BY region ORDER BY scans DESC""",
            (mid,),
        ).fetchall()
        by_product = db.execute(
            """SELECT p.id, p.name, p.sku, COUNT(l.id) AS scans,
                      COALESCE(SUM(l.points), 0) AS points
               FROM products p LEFT JOIN points_ledger l
                 ON l.product_id = p.id
               WHERE p.manufacturer_id = ?
               GROUP BY p.id ORDER BY scans DESC""",
            (mid,),
        ).fetchall()
        top_retailers = db.execute(
            """SELECT r.id, r.name, r.shop_name, r.region, COUNT(*) AS scans,
                      SUM(l.points) AS points
               FROM points_ledger l JOIN retailers r ON r.id = l.retailer_id
               WHERE l.manufacturer_id = ?
               GROUP BY r.id ORDER BY points DESC LIMIT 10""",
            (mid,),
        ).fetchall()
        map_points = db.execute(
            """SELECT r.id, r.name, r.shop_name, r.region, r.lat, r.lng,
                      COUNT(*) AS scans, SUM(l.points) AS points,
                      MAX(l.scanned_at) AS last_scan
               FROM points_ledger l JOIN retailers r ON r.id = l.retailer_id
               WHERE l.manufacturer_id = ?
                 AND r.lat IS NOT NULL AND r.lng IS NOT NULL
               GROUP BY r.id""",
            (mid,),
        ).fetchall()
    return {
        "totals": dict(totals),
        "by_region": [dict(r) for r in by_region],
        "by_product": [dict(r) for r in by_product],
        "top_retailers": [dict(r) for r in top_retailers],
        "map_points": [dict(r) for r in map_points],
    }


# ---------- webview pages + built panel ----------

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/panel/")

@app.get("/web/generate", include_in_schema=False)
def web_generate():
    return FileResponse(WEB_DIR / "generate.html")


@app.get("/web/scan", include_in_schema=False)
@app.get("/web/scan/{token}", include_in_schema=False)
def web_scan(token: str | None = None):
    return FileResponse(WEB_DIR / "scan.html")


if PANEL_DIST.exists():
    app.mount("/panel", StaticFiles(directory=PANEL_DIST, html=True),
              name="panel")

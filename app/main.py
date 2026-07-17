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
                   issue_token, new_temp_password, verify_password,
                   verify_sso_assertion)
from .database import IS_PG, create_constraints, get_db, init_db, migrate
from .geo import coords_for, known_places, nearest_city, reverse_address
from .pdf_service import build_pdf
from .qr_service import (new_manual_code, new_reference, new_token,
                         payload_for, render_png)
from .vastra_client import (VastraApiError, VastraRejection,
                            fetch_vastra_products, send_login_otp,
                            verify_login_otp)

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


def _backfill_product_snapshots() -> None:
    """One-time, idempotent backfill of the product reference/snapshot columns
    introduced by the Product System-of-Record migration. Fills only NULLs from
    the (transitional) products table so batches/scans created before the
    migration keep displaying correctly without a live products join. Safe to run
    on every startup; non-fatal if it cannot complete."""
    try:
        with get_db() as db:
            db.execute(
                """UPDATE qr_batches SET manufacturer_id = (
                       SELECT p.manufacturer_id FROM products p
                       WHERE p.id = qr_batches.product_id)
                   WHERE manufacturer_id IS NULL AND product_id IS NOT NULL""")
            db.execute(
                """UPDATE qr_batches SET product_name = (
                       SELECT p.name FROM products p
                       WHERE p.id = qr_batches.product_id)
                   WHERE product_name IS NULL AND product_id IS NOT NULL""")
            db.execute(
                """UPDATE qr_batches SET product_sku = (
                       SELECT p.sku FROM products p
                       WHERE p.id = qr_batches.product_id)
                   WHERE product_sku IS NULL AND product_id IS NOT NULL""")
            db.execute(
                """UPDATE points_ledger SET product_name = (
                       SELECT p.name FROM products p
                       WHERE p.id = points_ledger.product_id)
                   WHERE product_name IS NULL AND product_id IS NOT NULL""")
            db.execute(
                """UPDATE points_ledger SET product_sku = (
                       SELECT p.sku FROM products p
                       WHERE p.id = points_ledger.product_id)
                   WHERE product_sku IS NULL AND product_id IS NOT NULL""")
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate()
    create_constraints()
    _backfill_coords()
    _backfill_product_snapshots()
    yield


app = FastAPI(title="Loyalty QR API", version="4.0.0", lifespan=lifespan)

# Panel dev server. Same-origin in production, so this is dev-only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- rate limiting (Fix 4) ----------
# Pragmatic per-endpoint limits via slowapi. Authenticated endpoints are keyed
# by the bearer token (so one retailer can't exhaust another's budget when they
# share a NAT IP); login endpoints are keyed by client IP. Every limit is
# overridable by env var, and the whole feature can be switched off with
# RL_ENABLED=0. In-memory storage by default; set RL_STORAGE_URI (e.g. a redis://
# URL) when running more than one process.
import os as _os  # noqa: E402

from slowapi import Limiter, _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402

RL_ENABLED = _os.environ.get("RL_ENABLED", "1") != "0"
RL_LOGIN = _os.environ.get("RL_LOGIN", "10/minute")        # manuf + retailer login
RL_SCAN = _os.environ.get("RL_SCAN", "60/minute")          # generous for bulk scanning
RL_CLAIM = _os.environ.get("RL_CLAIM", "20/minute")
RL_QRGEN = _os.environ.get("RL_QRGEN", "30/minute")
RL_IMPORT = _os.environ.get("RL_IMPORT", "10/hour")


def _client_key(request: Request) -> str:
    """Rate-limit bucket key: the caller's bearer token (or ?token=) when
    present, else their IP. Keeps per-retailer limits independent on shared IPs."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if tok:
            return tok
    return request.query_params.get("token") or get_remote_address(request)


_limiter_kwargs = {"key_func": _client_key, "enabled": RL_ENABLED}
if _os.environ.get("RL_STORAGE_URI"):
    _limiter_kwargs["storage_uri"] = _os.environ["RL_STORAGE_URI"]
limiter = Limiter(**_limiter_kwargs)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------- schemas ----------

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class SsoIn(BaseModel):
    # A parent-app (Vastra / YourApp) signed HS256 JWT. Verified by
    # auth.verify_sso_assertion; the loyalty token is minted only if it checks out.
    assertion: str = Field(min_length=1, max_length=4096)


class ManufacturerIn(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)


class ProductPointsIn(BaseModel):
    points: int = Field(ge=0)


class RetailerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    shop_name: str = Field(min_length=1, max_length=200)
    # Optional: when left blank, the city is inferred from the retailer's
    # first scan location (reverse-geocoded to the nearest known city).
    region: str = Field(default="", max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    # Distributor this retailer belongs to (manuf -> distributor -> retailer).
    distributor_id: int | None = Field(default=None)
    # Manual override; when omitted, resolved from region city name
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    # Parent-system (YourApp) stable id, set at provisioning time so the SSO
    # exchange can resolve this retailer. Unique per manufacturer.
    external_id: str | None = Field(default=None, max_length=200)


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
    # New (primary) contract: Vastra is the product System of Record and sends a
    # reference (product_external_id) + immutable snapshot (name/sku) + the frozen
    # points value. Loyalty trusts it and never touches the products table.
    product_external_id: str | None = Field(default=None, max_length=200)
    product_name: str | None = Field(default=None, max_length=200)
    product_sku: str | None = Field(default=None, max_length=100)
    # Transitional/legacy: the loyalty product id used by the admin panel and the
    # /web/generate page. Used only when product_external_id is absent; resolved
    # once against the products table to build the same snapshot. Remove once those
    # clients call the Vastra backend instead.
    product_id: int | None = Field(default=None)
    quantity: int = Field(ge=1, le=10_000)
    points_per_code: int | None = Field(
        default=None, ge=0,
        description="Points frozen per code. Required with product_external_id; "
                    "with legacy product_id, defaults to the product's points.",
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
@limiter.limit(RL_LOGIN, key_func=get_remote_address)
def login(request: Request, body: LoginIn):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM manufacturers WHERE username = ?",
            (body.username.strip().lower(),),
        ).fetchone()
        if not row or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "Invalid username or password")
        if row["blocked"]:
            raise HTTPException(403, "Account is blocked")
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
        # Security: after logout the DB holds no live credentials for this
        # account — the stored Vastra access_token goes too (a fresh one is
        # minted on the next OTP login; no-op for password/admin logins).
        db.execute(
            "UPDATE manufacturers SET vastra_access_token = NULL WHERE id = ?",
            (user["id"],))
    return {"ok": True}


@app.post("/auth/sso/manufacturer")
@limiter.limit(RL_LOGIN, key_func=get_remote_address)
def sso_manufacturer(request: Request, body: SsoIn):
    """SSO exchange for the Vastra App: verify a parent-signed assertion and mint
    a normal loyalty manufacturer token. The manufacturer must already exist
    (imported by Vastra), matched by external_id; unknown principals are rejected,
    never created. Returns the same body as /auth/login."""
    claims = verify_sso_assertion(body.assertion, "manufacturer")
    external_id = str(claims["sub"]).strip()
    with get_db() as db:
        row = db.execute(
            """SELECT id, username, display_name, is_admin, blocked
               FROM manufacturers WHERE external_id = ?""",
            (external_id,),
        ).fetchone()
        if not row:
            raise HTTPException(403, "Manufacturer not provisioned")
        if row["blocked"]:
            raise HTTPException(403, "Account is blocked")
        token = issue_token(db, row["id"])
    return {
        "token": token,
        "display_name": row["display_name"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
    }


# ---------- manufacturer auth via Vastra OTP ----------
# The manufacturer logs in with their existing Vastra credentials: Vastra
# texts an OTP to the organization's registered mobile, we verify it with
# Vastra server-side, then find-or-create the manufacturer by
# external_id = organization_Id (first login auto-provisions — no second
# account) and mint the same opaque token /auth/login issues.

class VastraOtpSendIn(BaseModel):
    mobile: str = Field(min_length=8, max_length=15, pattern=r"^[0-9]+$")
    country_code: str = Field(default="+91", min_length=2, max_length=5,
                              pattern=r"^\+[0-9]+$")
    is_resend: int = Field(default=0, ge=0, le=1)


class VastraOtpVerifyIn(BaseModel):
    mobile: str = Field(min_length=8, max_length=15, pattern=r"^[0-9]+$")
    country_code: str = Field(default="+91", min_length=2, max_length=5,
                              pattern=r"^\+[0-9]+$")
    otp: str = Field(min_length=3, max_length=10, pattern=r"^[0-9]+$")


def _vastra_username(db, org: dict, external_id: str) -> str:
    """Derive a unique panel username for an auto-provisioned manufacturer
    (mirrors _assign_retailer_login: readable base, id-suffix on clash)."""
    raw = org.get("org_url") or org.get("organization_name") or ""
    base = "".join(c for c in raw.lower() if c.isalnum()) or f"vastra{external_id}"
    username = base
    if db.execute("SELECT 1 FROM manufacturers WHERE username = ?",
                  (username,)).fetchone():
        username = f"{base}{external_id}"
    return username


@app.post("/auth/vastra/send-otp")
@limiter.limit(RL_LOGIN, key_func=get_remote_address)
def vastra_send_otp(request: Request, body: VastraOtpSendIn):
    """Step 1: have Vastra text an OTP to the org's registered mobile."""
    try:
        message = send_login_otp(body.country_code, body.mobile, body.is_resend)
    except VastraRejection as exc:
        raise HTTPException(403, exc.message)
    except VastraApiError as exc:
        raise HTTPException(502, f"Vastra login service unavailable: {exc}")
    return {"ok": True, "message": message}


@app.post("/auth/vastra/verify-otp")
@limiter.limit(RL_LOGIN, key_func=get_remote_address)
def vastra_verify_otp(request: Request, body: VastraOtpVerifyIn):
    """Step 2: verify the OTP with Vastra, log the manufacturer in.
    Stores Vastra's access_token server-side (used to pull the org's design
    list; wiped again on logout). Returns the same body as /auth/login."""
    try:
        org = verify_login_otp(body.country_code, body.mobile, body.otp)
    except VastraRejection as exc:
        raise HTTPException(401, exc.message)
    except VastraApiError as exc:
        raise HTTPException(502, f"Vastra login service unavailable: {exc}")
    external_id = str(org["organization_Id"]).strip()
    display_name = ((org.get("organization_name") or "").strip()
                    or f"Vastra org {external_id}")
    with get_db() as db:
        row = db.execute(
            """SELECT id, username, is_admin, blocked
               FROM manufacturers WHERE external_id = ?""",
            (external_id,),
        ).fetchone()
        if row and row["blocked"]:
            raise HTTPException(403, "Account is blocked")
        if row:
            mid, username = row["id"], row["username"]
            is_admin = bool(row["is_admin"])
            db.execute(
                """UPDATE manufacturers
                   SET display_name = ?, vastra_access_token = ?
                   WHERE id = ?""",
                (display_name, org["access_token"], mid))
        else:
            username = _vastra_username(db, org, external_id)
            # Random throwaway password: OTP-provisioned accounts log in via
            # Vastra only; nobody ever knows this password.
            cur = db.execute(
                """INSERT INTO manufacturers
                   (username, password_hash, display_name, external_id,
                    vastra_access_token)
                   VALUES (?, ?, ?, ?, ?)""",
                (username, hash_password(new_temp_password()), display_name,
                 external_id, org["access_token"]))
            mid, is_admin = cur.lastrowid, False
        token = issue_token(db, mid)
    return {
        "token": token,
        "display_name": display_name,
        "username": username,
        "is_admin": is_admin,
    }


# ---------- retailer auth (YourApp side) ----------

@app.post("/auth/retailer/login")
@limiter.limit(RL_LOGIN, key_func=get_remote_address)
def retailer_login(request: Request, body: LoginIn):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM retailers WHERE username = ?",
            (body.username.strip().lower(),),
        ).fetchone()
        if (not row or not row["password_hash"]
                or not verify_password(body.password, row["password_hash"])):
            raise HTTPException(401, "Invalid username or password")
        if row["blocked"]:
            raise HTTPException(403, "Account is blocked")
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
        # Fix 3: tells the client to prompt for a password change on first login
        # (set for retailers created with a system-generated temp password).
        "must_change": bool(row["must_change"]),
    }


@app.post("/auth/sso/retailer")
@limiter.limit(RL_LOGIN, key_func=get_remote_address)
def sso_retailer(request: Request, body: SsoIn):
    """SSO exchange for YourApp: verify a parent-signed assertion and mint a normal
    loyalty retailer token. The retailer must already be provisioned by its
    manufacturer (with external_id); unknown retailers are rejected, never created.
    manufacturer_external_id scopes the lookup to the correct tenant, so one
    parent's id space can't resolve into another. Same body as /auth/retailer/login
    (minus must_change — SSO does not use a loyalty password)."""
    claims = verify_sso_assertion(body.assertion, "retailer")
    external_id = str(claims["sub"]).strip()
    manuf_external = str(claims.get("manufacturer_external_id") or "").strip()
    if not manuf_external:
        raise HTTPException(401, "Assertion missing manufacturer_external_id")
    with get_db() as db:
        manuf = db.execute(
            "SELECT id, display_name FROM manufacturers WHERE external_id = ?",
            (manuf_external,),
        ).fetchone()
        if not manuf:
            raise HTTPException(403, "Manufacturer not provisioned")
        row = db.execute(
            """SELECT * FROM retailers
               WHERE manufacturer_id = ? AND external_id = ?""",
            (manuf["id"], external_id),
        ).fetchone()
        if not row:
            raise HTTPException(403, "Retailer not provisioned")
        if row["blocked"]:
            raise HTTPException(403, "Account is blocked")
        token = issue_retailer_token(db, row["id"])
    return {
        "token": token,
        "retailer_id": row["id"],
        "shop_name": row["shop_name"],
        "name": row["name"],
        "region": row["region"],
        "manufacturer": manuf["display_name"],
    }


class RetailerPasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@app.post("/retailer/password")
def change_retailer_password(body: RetailerPasswordIn,
                             retailer: dict = Depends(current_retailer)):
    """Retailer sets a new password. Verifies the current one, stores only the
    PBKDF2 hash, and clears the must_change flag. Lets a retailer move off the
    system-generated temporary password (Fix 3)."""
    if body.new_password == body.current_password:
        raise HTTPException(422, "New password must differ from the current one")
    with get_db() as db:
        row = db.execute(
            "SELECT password_hash FROM retailers WHERE id = ?",
            (retailer["id"],),
        ).fetchone()
        if (not row or not row["password_hash"]
                or not verify_password(body.current_password,
                                       row["password_hash"])):
            raise HTTPException(401, "Current password is incorrect")
        db.execute(
            "UPDATE retailers SET password_hash = ?, must_change = 0 "
            "WHERE id = ?",
            (hash_password(body.new_password), retailer["id"]),
        )
    return {"ok": True}


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
        "must_change": bool(retailer["must_change"]),
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
# CRUD is gone: Vastra owns the product catalog now (see /vastra/products
# below). GET /products stays for legacy readers (Schemes, Claims, and the
# /web/generate demo webview) that still key off the local table's rows —
# no new rows are written to it going forward.

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


# ---------- Vastra product catalog (manufacturer-scoped) ----------
# Vastra is the system of record for the product itself; the manufacturer
# still controls the loyalty points value per product, stored locally in
# product_points and merged onto Vastra's live list below.

@app.get("/vastra/products")
def list_vastra_products(user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        row = db.execute(
            "SELECT vastra_access_token FROM manufacturers WHERE id = ?",
            (user["id"],)).fetchone()
    vastra_token = row["vastra_access_token"] if row else None
    if not vastra_token:
        # Password-login accounts (or a session that outlived a logout wipe)
        # have no Vastra credential to pull the catalog with.
        raise HTTPException(
            409, "No Vastra session — log in with Vastra OTP to load the "
                 "product catalog")
    try:
        products = fetch_vastra_products(vastra_token)
    except VastraRejection as exc:
        raise HTTPException(
            502, f"Vastra rejected the product request: {exc.message} — "
                 "logging out and back in refreshes the Vastra session")
    except VastraApiError as exc:
        raise HTTPException(502, f"Vastra product service unavailable: {exc}")
    with get_db() as db:
        overrides = {
            r["product_external_id"]: r["points"]
            for r in db.execute(
                "SELECT product_external_id, points FROM product_points "
                "WHERE manufacturer_id = ?", (user["id"],))
        }
    return [{**p, "points": overrides.get(p["external_id"], 0)}
            for p in products]


@app.put("/vastra/products/{external_id}/points")
def set_product_points(external_id: str, body: ProductPointsIn,
                       user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM product_points WHERE manufacturer_id = ? "
            "AND product_external_id = ?", (user["id"], external_id),
        ).fetchone()
        if row:
            db.execute(
                "UPDATE product_points SET points = ?, "
                "updated_at = datetime('now') WHERE manufacturer_id = ? "
                "AND product_external_id = ?",
                (body.points, user["id"], external_id),
            )
        else:
            db.execute(
                "INSERT INTO product_points "
                "(manufacturer_id, product_external_id, points) "
                "VALUES (?, ?, ?)",
                (user["id"], external_id, body.points),
            )
    return {"external_id": external_id, "points": body.points}


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
    external_id = (body.external_id or "").strip() or None
    with get_db() as db:
        distributor_id = _distributor_id_for(db, user["id"], body.distributor_id)
        try:
            cur = db.execute(
                """INSERT INTO retailers
                   (manufacturer_id, name, shop_name, region, phone, lat, lng,
                    location_source, distributor_id, external_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user["id"], body.name, body.shop_name, region, body.phone,
                 lat, lng, source, distributor_id, external_id),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, "external_id already in use")
            raise
        rid = cur.lastrowid
        username, password = _assign_retailer_login(db, body.shop_name, rid)
        row = db.execute(
            "SELECT * FROM retailers WHERE id = ?", (rid,)
        ).fetchone()
    out = _clean_retailer(row)
    # Plaintext password is returned only here, at creation, so the panel can
    # show the manufacturer the credentials to hand to the retailer.
    out["login_username"] = username
    out["login_password"] = password
    return out


def _assign_retailer_login(db, shop_name: str, rid: int) -> tuple[str, str]:
    """Derive and store a retailer login: username = first alphanumeric word of
    the shop name (lowercased); password = a cryptographically random temporary
    password (Fix 3 — no longer the guessable ``<username>123``). A username
    clash gets the id appended so the UNIQUE constraint always holds. The login
    is flagged must_change=1 so the client can prompt for a reset on first use.
    Returns (username, plaintext temporary pw) — surfaced once at creation so
    the panel can show the manufacturer the credentials to hand over."""
    first = (shop_name.split() or ["shop"])[0].lower()
    base = "".join(ch for ch in first if ch.isalnum()) or "shop"
    username = base
    if db.execute("SELECT 1 FROM retailers WHERE username = ?",
                  (username,)).fetchone():
        username = f"{base}{rid}"
    password = new_temp_password()
    db.execute(
        "UPDATE retailers SET username = ?, password_hash = ?, must_change = 1 "
        "WHERE id = ?",
        (username, hash_password(password), rid),
    )
    return username, password


def _find_or_create_distributor(db, mid: int, name: str) -> int | None:
    """Resolve a distributor by name within a manufacturer, creating it if new.
    Returns its id, or None when the name is blank."""
    name = (name or "").strip()
    if not name:
        return None
    row = db.execute(
        """SELECT id FROM distributors
           WHERE manufacturer_id = ? AND LOWER(name) = LOWER(?)""",
        (mid, name),
    ).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO distributors (manufacturer_id, name) VALUES (?, ?)",
        (mid, name),
    )
    return cur.lastrowid


def _distributor_id_for(db, mid: int, distributor_id):
    """Validate that a distributor_id (if given) belongs to this manufacturer."""
    if distributor_id is None:
        return None
    ok = db.execute(
        "SELECT 1 FROM distributors WHERE id = ? AND manufacturer_id = ?",
        (distributor_id, mid),
    ).fetchone()
    if not ok:
        raise HTTPException(400, "Distributor not found")
    return distributor_id


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
                      d.name AS distributor_name,
                      (SELECT COUNT(*) FROM points_ledger l
                       WHERE l.retailer_id = r.id AND l.entry_type = 'scan')
                          AS scans,
                      (SELECT COALESCE(SUM(points), 0) FROM points_ledger l
                       WHERE l.retailer_id = r.id) AS points
               FROM retailers r
               LEFT JOIN distributors d ON d.id = r.distributor_id
               WHERE r.manufacturer_id = ? ORDER BY r.id""",
            (user["id"],),
        ).fetchall()
    return [_clean_retailer(r) for r in rows]


class RetailerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    shop_name: str | None = Field(default=None, min_length=1, max_length=200)
    region: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    # Nullable on purpose: sending an explicit null unassigns the distributor.
    distributor_id: int | None = Field(default=None)


@app.patch("/retailers/{retailer_id}")
def update_retailer(retailer_id: int, body: RetailerUpdate,
                    user: dict = Depends(current_manufacturer)):
    # distributor_id is handled separately so an explicit null can unassign it
    # (the None-filter below would otherwise drop it).
    fields = {k: v for k, v in body.model_dump().items()
              if v is not None and k != "distributor_id"}
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM retailers WHERE id = ? AND manufacturer_id = ?",
            (retailer_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Retailer not found")
        if "distributor_id" in body.model_fields_set:
            fields["distributor_id"] = _distributor_id_for(
                db, user["id"], body.distributor_id)
        if not fields:
            raise HTTPException(422, "Nothing to update")
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
                      l.product_name AS product_name,
                      l.product_sku AS sku, s.name AS scheme_name
               FROM points_ledger l
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
    """Refresh the shop's exact pin, city, and street address from where the
    retailer actually scanned — **latest wins**, every scanning session. A wrong
    city entered at registration self-corrects to the real one, and the
    manufacturer gets a precise, visitable address. The address is reverse-
    geocoded best-effort; if that lookup fails we keep the previous address (the
    'View on map' link still works from the fresh coordinates)."""
    rid = retailer["id"]
    city = nearest_city(body.lat, body.lng)
    address = reverse_address(body.lat, body.lng)
    with get_db() as db:
        db.execute(
            """UPDATE retailers SET lat = ?, lng = ?, location_source = 'gps',
                   region = COALESCE(?, region), address = COALESCE(?, address)
               WHERE id = ?""",
            (body.lat, body.lng, city, address, rid),
        )
    return {"updated": True, "region": city, "address": address}


# ---------- distributors (manufacturer-scoped) ----------

class DistributorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    region: str | None = Field(default=None, max_length=100)


class DistributorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    region: str | None = Field(default=None, max_length=100)


@app.post("/distributors", status_code=201)
def create_distributor(body: DistributorIn,
                       user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO distributors (manufacturer_id, name, phone, region)
               VALUES (?, ?, ?, ?)""",
            (user["id"], body.name.strip(), body.phone, body.region),
        )
        row = db.execute(
            "SELECT * FROM distributors WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


@app.get("/distributors")
def list_distributors(user: dict = Depends(current_manufacturer)):
    with get_db() as db:
        rows = db.execute(
            """SELECT d.*,
                      (SELECT COUNT(*) FROM retailers r
                       WHERE r.distributor_id = d.id) AS retailers,
                      (SELECT COUNT(*) FROM points_ledger l
                       WHERE l.distributor_id = d.id
                         AND l.entry_type = 'scan') AS scans,
                      (SELECT COALESCE(SUM(points), 0) FROM points_ledger l
                       WHERE l.distributor_id = d.id
                         AND l.entry_type = 'scan') AS points
               FROM distributors d
               WHERE d.manufacturer_id = ? ORDER BY d.name""",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.patch("/distributors/{distributor_id}")
def update_distributor(distributor_id: int, body: DistributorUpdate,
                       user: dict = Depends(current_manufacturer)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(422, "Nothing to update")
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM distributors WHERE id = ? AND manufacturer_id = ?",
            (distributor_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Distributor not found")
        sets = ", ".join(f"{k} = ?" for k in fields)
        db.execute(
            f"UPDATE distributors SET {sets} WHERE id = ?",
            [*fields.values(), distributor_id],
        )
        out = db.execute(
            "SELECT * FROM distributors WHERE id = ?", (distributor_id,)
        ).fetchone()
    return dict(out)


@app.delete("/distributors/{distributor_id}", status_code=204)
def delete_distributor(distributor_id: int,
                       user: dict = Depends(current_manufacturer)):
    """Deleting a distributor unlinks its retailers (they are NOT deleted).
    Past scans keep their recorded distributor_id (point-in-time history)."""
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM distributors WHERE id = ? AND manufacturer_id = ?",
            (distributor_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Distributor not found")
        db.execute(
            """UPDATE retailers SET distributor_id = NULL
               WHERE distributor_id = ? AND manufacturer_id = ?""",
            (distributor_id, user["id"]),
        )
        db.execute("DELETE FROM distributors WHERE id = ?", (distributor_id,))


class ImportIn(BaseModel):
    csv: str = Field(min_length=1, description="Raw CSV text")


@app.post("/retailers/import")
@limiter.limit(RL_IMPORT)
def import_retailers_csv(request: Request, body: ImportIn,
                         user: dict = Depends(current_manufacturer)):
    """Bulk-create retailers from CSV text. Columns (header row, case-insensitive):
    shop_name (required), name, region, phone, distributor, external_id (optional).
    external_id is the parent-system (YourApp) id used by the SSO exchange; it is
    unique per manufacturer. Each retailer gets an auto-login; the distributor is
    found-or-created by name and linked. Rows whose shop_name already exists for
    this manufacturer are skipped. Returns generated credentials so the panel can
    show them once."""
    import csv as csvmod
    import io
    mid = user["id"]
    reader = csvmod.DictReader(io.StringIO(body.csv))
    headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    if "shop_name" not in headers:
        raise HTTPException(422, "CSV must have a 'shop_name' column")
    created = skipped = 0
    errors: list[str] = []
    credentials: list[dict] = []
    with get_db() as db:
        for i, raw in enumerate(reader, start=2):  # row 1 is the header
            row = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in raw.items()}
            shop = row.get("shop_name", "")
            if not shop:
                errors.append(f"row {i}: missing shop_name")
                continue
            dup = db.execute(
                """SELECT 1 FROM retailers
                   WHERE manufacturer_id = ? AND LOWER(shop_name) = LOWER(?)""",
                (mid, shop),
            ).fetchone()
            if dup:
                skipped += 1
                continue
            external_id = row.get("external_id", "") or None
            if external_id and db.execute(
                """SELECT 1 FROM retailers
                   WHERE manufacturer_id = ? AND external_id = ?""",
                (mid, external_id),
            ).fetchone():
                skipped += 1
                errors.append(f"row {i}: external_id '{external_id}' already in use")
                continue
            region = row.get("region", "")
            coords = coords_for(region) if region else None
            lat, lng = coords if coords else (None, None)
            distributor_id = _find_or_create_distributor(
                db, mid, row.get("distributor", ""))
            cur = db.execute(
                """INSERT INTO retailers
                   (manufacturer_id, name, shop_name, region, phone, lat, lng,
                    location_source, distributor_id, external_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, row.get("name", "") or shop, shop, region,
                 row.get("phone", "") or None, lat, lng,
                 "city" if coords else None, distributor_id, external_id),
            )
            username, password = _assign_retailer_login(db, shop, cur.lastrowid)
            created += 1
            credentials.append(
                {"shop_name": shop, "username": username, "password": password})
    return {"created": created, "skipped": skipped,
            "errors": errors, "credentials": credentials}


@app.post("/distributors/import")
@limiter.limit(RL_IMPORT)
def import_distributors_csv(request: Request, body: ImportIn,
                            user: dict = Depends(current_manufacturer)):
    """Bulk-create distributors from CSV text. Columns (header row,
    case-insensitive): name (required), phone, region. Rows whose name already
    exists for this manufacturer are skipped."""
    import csv as csvmod
    import io
    mid = user["id"]
    reader = csvmod.DictReader(io.StringIO(body.csv))
    headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    if "name" not in headers:
        raise HTTPException(422, "CSV must have a 'name' column")
    created = skipped = 0
    errors: list[str] = []
    with get_db() as db:
        for i, raw in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in raw.items()}
            name = row.get("name", "")
            if not name:
                errors.append(f"row {i}: missing name")
                continue
            if db.execute(
                """SELECT 1 FROM distributors
                   WHERE manufacturer_id = ? AND LOWER(name) = LOWER(?)""",
                (mid, name),
            ).fetchone():
                skipped += 1
                continue
            db.execute(
                """INSERT INTO distributors (manufacturer_id, name, phone, region)
                   VALUES (?, ?, ?, ?)""",
                (mid, name, row.get("phone", "") or None,
                 row.get("region", "") or None),
            )
            created += 1
    return {"created": created, "skipped": skipped, "errors": errors}


# ---------- QR generation (manufacturer-scoped) ----------

@app.post("/qr/generate", status_code=201)
@limiter.limit(RL_QRGEN)
def generate_qr_batch(request: Request, body: GenerateIn,
                      user: dict = Depends(current_manufacturer)):
    mid = user["id"]
    # Resolve the product snapshot for this batch.
    #  Primary path: Vastra (the product System of Record) supplies a reference
    #  (product_external_id) + snapshot (name/sku) + the frozen points value;
    #  loyalty trusts it and never reads the products table.
    #  Transitional path: the panel / /web/generate still send a loyalty
    #  product_id, looked up once to build the same snapshot.
    product_id = None
    if body.product_external_id:
        if not (body.product_name and body.product_sku
                and body.points_per_code is not None):
            raise HTTPException(
                422, "product_name, product_sku and points_per_code are "
                     "required with product_external_id")
        product_external_id = body.product_external_id.strip()
        product_name, product_sku = body.product_name, body.product_sku
        points = body.points_per_code
    elif body.product_id is not None:
        with get_db() as db:
            product = db.execute(
                "SELECT * FROM products WHERE id = ? AND manufacturer_id = ?",
                (body.product_id, mid),
            ).fetchone()
        if not product:
            raise HTTPException(404, "Product not found")
        product_id = product["id"]
        product_external_id = None
        product_name, product_sku = product["name"], product["sku"]
        points = (body.points_per_code if body.points_per_code is not None
                  else product["loyalty_points"])
    else:
        raise HTTPException(
            422, "product_external_id (or legacy product_id) is required")

    with get_db() as db:
        # manufacturer_id is stored directly on the batch (no products join);
        # points_per_code stays frozen exactly as before.
        cur = db.execute(
            """INSERT INTO qr_batches
               (manufacturer_id, product_id, product_external_id,
                product_name, product_sku, quantity, points_per_code)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mid, product_id, product_external_id, product_name, product_sku,
             body.quantity, points),
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
        "product_id": product_id,
        "product_external_id": product_external_id,
        "product_name": product_name,
        "product_sku": product_sku,
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
        """SELECT b.*, b.product_sku AS sku
           FROM qr_batches b
           WHERE b.id = ? AND b.manufacturer_id = ?""",
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
    sql = """SELECT b.*, b.product_sku AS sku
             FROM qr_batches b
             WHERE b.manufacturer_id = ?"""
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
@limiter.limit(RL_SCAN)
def scan(request: Request, body: ScanIn,
         retailer: dict = Depends(current_retailer)):
    """Redeem a code by QR token or 6-char manual code. Points always go to
    the logged-in retailer, so a code can't be credited to another account.
    Single authority for rewards: base points + best active scheme bonus."""
    rid = retailer["id"]
    code = body.code.strip().replace("-", "").replace(" ", "").upper()
    with get_db() as db:
        row = db.execute(
            """SELECT c.token, c.redeemed_at, c.is_parent, b.points_per_code,
                      b.product_id AS product_id,
                      b.product_external_id AS product_external_id,
                      b.product_name AS product_name, b.product_sku AS sku,
                      b.manufacturer_id
               FROM qr_codes c
               JOIN qr_batches b ON b.id = c.batch_id
               WHERE c.token = ? OR c.manual_code = ?""",
            (body.code.strip(), code),
        ).fetchone()
        # Fix 5 (enumeration oracle): a non-existent code and a code that
        # belongs to another manufacturer return the *identical* 404, so an
        # attacker cannot use the response to tell a real cross-tenant code
        # from a fake one. "Already redeemed" stays distinct below because the
        # retailer needs that feedback and it only ever leaks the state of a
        # code they already legitimately hold.
        if not row or retailer["manufacturer_id"] != row["manufacturer_id"]:
            raise HTTPException(404, "Invalid code")

        # A box (parent) code registers all of its still-unredeemed children;
        # a plain code registers just itself. The actual race-safe redemption
        # happens via the conditional UPDATE below — these reads only drive
        # the not-yet-redeemed error message for the non-concurrent case.
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

        # Fix 1 (double-spend race): claim each child token with a *conditional*
        # UPDATE that only matches a still-unredeemed row, then credit points
        # ONLY for the rows this transaction actually won. Under concurrency the
        # database serializes these row updates; the loser sees rowcount == 0
        # (the row was redeemed by the winner) and credits nothing. This makes
        # the check-and-mark a single atomic database operation instead of the
        # previous read-then-write TOCTOU. The partial UNIQUE index on
        # points_ledger(token) is the belt-and-suspenders backstop.
        credited = []
        for t in tokens:
            cur = db.execute(
                """UPDATE qr_codes SET redeemed_at = datetime('now'),
                                       redeemed_by = ?
                   WHERE token = ? AND redeemed_at IS NULL""",
                (rid, t),
            )
            if cur.rowcount != 1:
                continue  # another concurrent scan already claimed this token
            db.execute(
                """INSERT INTO points_ledger
                   (manufacturer_id, retailer_id, token, product_id,
                    product_external_id, product_name, product_sku, points,
                    base_points, bonus_points, scheme_id, region, lat, lng,
                    distributor_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["manufacturer_id"], rid, t,
                 row["product_id"], row["product_external_id"],
                 row["product_name"], row["sku"], per, base, bonus,
                 scheme["id"] if scheme else None, retailer["region"],
                 body.lat, body.lng, retailer["distributor_id"]),
            )
            credited.append(t)

        # If a concurrent request beat us to every token, nothing was credited.
        if not credited:
            raise HTTPException(
                409, "Box already redeemed" if row["is_parent"]
                else "Code already redeemed")
        if row["is_parent"]:
            # Mark the box itself redeemed (conditional, so the loser is a no-op).
            db.execute(
                """UPDATE qr_codes SET redeemed_at = datetime('now'),
                                       redeemed_by = ?
                   WHERE token = ? AND redeemed_at IS NULL""",
                (rid, row["token"]),
            )

        count = len(credited)
        balance = db.execute(
            "SELECT COALESCE(SUM(points), 0) AS total FROM points_ledger"
            " WHERE retailer_id = ?",
            (rid,),
        ).fetchone()["total"]

    return {
        "redeemed": True,
        "is_box": bool(row["is_parent"]),
        "items_registered": count,
        "product": {"id": row["product_id"],
                    "external_id": row["product_external_id"],
                    "name": row["product_name"], "sku": row["sku"]},
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
    product_external_id: str | None = None,
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
    if product_id is not None:  # legacy/transitional filter
        where += " AND l.product_id = ?"
        args.append(product_id)
    if product_external_id is not None:
        where += " AND l.product_external_id = ?"
        args.append(product_external_id)
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

    # A box (parent) scan writes one ledger row per child code; collapse those
    # into a single claim so the list isn't flooded with duplicate retailer
    # rows. Children of one box share the same qr_codes.parent_token (a box is
    # scanned once), so COALESCE(parent_token, token) is a stable group key —
    # NULL parent_token (plain scans) groups on the unique token, i.e. one row
    # each. Done at query time, so it also tidies existing data (no migration).
    group_key = "COALESCE(q.parent_token, l.token)"
    with get_db() as db:
        total = db.execute(
            f"""SELECT COUNT(*) AS n FROM (
                  SELECT 1 FROM points_ledger l
                  JOIN qr_codes q ON q.token = l.token
                  {where} GROUP BY {group_key}
                ) sub""",
            args,
        ).fetchone()["n"]
        rows = db.execute(
            f"""SELECT MIN(l.id) AS id, l.scanned_at,
                       COUNT(*) AS item_count,
                       SUM(l.points) AS points,
                       SUM(l.base_points) AS base_points,
                       SUM(l.bonus_points) AS bonus_points,
                       l.region, MAX(q.parent_token) AS parent_token,
                       {group_key} AS token,
                       l.product_id AS product_id,
                       MAX(l.product_external_id) AS product_external_id,
                       MAX(l.product_name) AS product_name,
                       MAX(l.product_sku) AS sku,
                       r.id AS retailer_id, r.name AS retailer_name,
                       r.shop_name, r.lat, r.lng,
                       s.id AS scheme_id, s.name AS scheme_name
                FROM points_ledger l
                JOIN qr_codes q ON q.token = l.token
                JOIN retailers r ON r.id = l.retailer_id
                LEFT JOIN schemes s ON s.id = l.scheme_id
                {where}
                GROUP BY {group_key}, l.scanned_at, l.region,
                         l.product_id,
                         r.id, r.name, r.shop_name, r.lat, r.lng,
                         s.id, s.name
                ORDER BY l.scanned_at DESC LIMIT ? OFFSET ?""",
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
                  WHERE b.manufacturer_id = :m) AS codes_issued,
                 (SELECT COUNT(*) FROM gift_claims
                  WHERE manufacturer_id = :m) AS redeem_total,
                 (SELECT COUNT(*) FROM gift_claims
                  WHERE manufacturer_id = :m AND status = 'pending')
                     AS redeem_pending,
                 (SELECT COUNT(*) FROM gift_claims
                  WHERE manufacturer_id = :m AND status = 'approved')
                     AS redeem_approved""",
            {"m": mid},
        ).fetchone()
        by_region = db.execute(
            """SELECT COALESCE(NULLIF(region, ''), 'Unspecified') AS region,
                      COUNT(*) AS scans, SUM(points) AS points
               FROM points_ledger WHERE manufacturer_id = ?
                 AND entry_type = 'scan'
               GROUP BY COALESCE(NULLIF(region, ''), 'Unspecified')
               ORDER BY scans DESC""",
            (mid,),
        ).fetchall()
        # Grouped by the product reference from scan ledger snapshots (no products
        # join). Key falls back external_id -> sku -> legacy product_id so both
        # new (Vastra) and pre-migration rows group correctly. Note: only products
        # with scan activity appear (loyalty is no longer the product catalog).
        by_product = db.execute(
            """SELECT COALESCE(l.product_external_id, l.product_sku,
                               CAST(l.product_id AS TEXT)) AS id,
                      MAX(l.product_name) AS name,
                      MAX(l.product_sku) AS sku,
                      MAX(l.product_external_id) AS product_external_id,
                      COUNT(l.id) AS scans,
                      COALESCE(SUM(l.points), 0) AS points
               FROM points_ledger l
               WHERE l.manufacturer_id = ? AND l.entry_type = 'scan'
               GROUP BY COALESCE(l.product_external_id, l.product_sku,
                                 CAST(l.product_id AS TEXT))
               ORDER BY scans DESC""",
            (mid,),
        ).fetchall()
        by_distributor = db.execute(
            """SELECT d.id, d.name,
                      (SELECT COUNT(*) FROM retailers r
                       WHERE r.distributor_id = d.id) AS retailers,
                      COUNT(l.id) AS scans,
                      COALESCE(SUM(l.points), 0) AS points
               FROM distributors d
               LEFT JOIN points_ledger l
                 ON l.distributor_id = d.id AND l.entry_type = 'scan'
               WHERE d.manufacturer_id = ?
               GROUP BY d.id, d.name ORDER BY scans DESC""",
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
        # Monthly QR generation vs scans. Month bucket is substr(...,1,7) ->
        # 'YYYY-MM', portable across both SQLite and Postgres (no strftime).
        gen_rows = db.execute(
            """SELECT substr(c.created_at, 1, 7) AS month, COUNT(*) AS n
               FROM qr_codes c
               JOIN qr_batches b ON b.id = c.batch_id
               WHERE b.manufacturer_id = ?
               GROUP BY substr(c.created_at, 1, 7)""",
            (mid,),
        ).fetchall()
        scan_month_rows = db.execute(
            """SELECT substr(scanned_at, 1, 7) AS month, COUNT(*) AS n
               FROM points_ledger
               WHERE manufacturer_id = ? AND entry_type = 'scan'
               GROUP BY substr(scanned_at, 1, 7)""",
            (mid,),
        ).fetchall()
        # One dot per place a retailer actually scanned: use the per-scan GPS
        # captured at scan time, falling back to the retailer's pinned shop
        # coords for scans recorded without a location. Bucketed in Python by
        # ~11m (4 decimals) so repeated scans at one spot collapse to a single
        # weighted dot while distinct spots stay separate (the panel map clusters
        # nearby dots for display); keeps the SQL backend-portable.
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
        lat, lng = round(s["lat"], 4), round(s["lng"], 4)
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
    # Merge generation + scan counts into one {month, generated, scanned} series.
    months: dict[str, dict] = {}
    for row in gen_rows:
        m = row["month"]
        if m:
            months.setdefault(m, {"month": m, "generated": 0, "scanned": 0})
            months[m]["generated"] = row["n"]
    for row in scan_month_rows:
        m = row["month"]
        if m:
            months.setdefault(m, {"month": m, "generated": 0, "scanned": 0})
            months[m]["scanned"] = row["n"]
    by_month = [months[m] for m in sorted(months)]
    return {
        "totals": dict(totals),
        "by_region": [dict(r) for r in by_region],
        "by_product": [dict(r) for r in by_product],
        "by_distributor": [dict(r) for r in by_distributor],
        "top_retailers": [dict(r) for r in top_retailers],
        "map_points": [dict(r) for r in map_points],
        "by_month": by_month,
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
@limiter.limit(RL_CLAIM)
def claim_gift(request: Request, body: GiftClaimIn,
               retailer: dict = Depends(current_retailer)):
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
        # Fix 2 (claim double-spend race): serialize concurrent claims for this
        # retailer by taking a row lock on the retailer BEFORE reading the
        # balance. On PostgreSQL, SELECT ... FOR UPDATE makes a second
        # simultaneous claim block until the first commits, so it then re-reads
        # the already-reduced balance and is correctly rejected — a wallet can
        # never go negative. SQLite serializes writers at the database level, so
        # no explicit lock clause is needed (and it has no FOR UPDATE syntax).
        if IS_PG:
            db.execute("SELECT id FROM retailers WHERE id = ? FOR UPDATE", (rid,))
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


@app.get("/web/vastra-logo.png", include_in_schema=False)
def web_logo():
    return FileResponse(WEB_DIR / "vastra-logo.png", media_type="image/png")


if PANEL_DIST.exists():
    app.mount("/panel", StaticFiles(directory=PANEL_DIST, html=True),
              name="panel")

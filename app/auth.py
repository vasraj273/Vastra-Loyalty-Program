"""Authentication: password hashing, bearer tokens, route dependencies.

Tokens are opaque random strings stored in the auth_tokens table. Clients
send `Authorization: Bearer <token>`; a `?token=` query parameter is also
accepted so plain links (the print-PDF tab) can authenticate.
"""

import hashlib
import os
import secrets
import time

import jwt  # PyJWT
from fastapi import HTTPException, Request

from .database import get_db

_ITERATIONS = 200_000

# ---------- SSO assertion verification (Vastra / YourApp -> loyalty) ----------
# A parent backend (which already authenticated the user) mints a short-lived
# HS256 JWT; the loyalty SSO exchange endpoints verify it here and then issue a
# normal loyalty token. Shared secret per environment, like QR_BASE_URL /
# DATABASE_URL. Config is read at import time from the environment.
SSO_SECRET = os.environ.get("SSO_SECRET")
SSO_AUDIENCE = os.environ.get("SSO_AUDIENCE", "loyalty")
SSO_ISSUERS = [s.strip() for s in
               os.environ.get("SSO_ISSUERS", "vastra,yourapp").split(",")
               if s.strip()]
# Max accepted age of an assertion (seconds), bounding the replay window even if
# a parent sets a longer exp. The assertion is single-use in spirit, not stored.
SSO_MAX_AGE = int(os.environ.get("SSO_MAX_AGE", "120"))


def verify_sso_assertion(assertion: str, expected_role: str) -> dict:
    """Verify a parent-app SSO JWT and return its claims, or raise HTTPException.

    Forgery, replay, and role/tenant confusion are all rejected here:
    - signature + algorithm are pinned to HS256 (``alg:none`` and any other alg
      are refused by PyJWT),
    - ``aud`` must equal SSO_AUDIENCE and ``iss`` must be an allowed issuer,
    - ``exp`` is enforced by PyJWT and ``iat`` must be within SSO_MAX_AGE,
    - ``role`` must match the endpoint (manufacturer assertions can't be replayed
      at the retailer endpoint or vice versa).
    Identity is taken only from the signed ``sub`` (the parent external_id).
    """
    if not SSO_SECRET:
        raise HTTPException(503, "SSO is not configured")
    try:
        claims = jwt.decode(
            assertion,
            SSO_SECRET,
            algorithms=["HS256"],
            audience=SSO_AUDIENCE,
            leeway=10,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid SSO assertion")
    if SSO_ISSUERS and claims.get("iss") not in SSO_ISSUERS:
        raise HTTPException(401, "Invalid SSO assertion")
    if claims.get("role") != expected_role:
        raise HTTPException(401, "Invalid SSO assertion")
    iat = claims.get("iat")
    if not isinstance(iat, (int, float)) or time.time() - iat > SSO_MAX_AGE:
        raise HTTPException(401, "SSO assertion expired")
    if not str(claims.get("sub") or "").strip():
        raise HTTPException(401, "Invalid SSO assertion")
    return claims


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS
    ).hex()
    return f"{salt}${digest}"


# Unambiguous alphabet (no O/0/I/l/1) so a manufacturer can read a generated
# temporary password aloud to a retailer without confusion.
_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def new_temp_password(length: int = 12) -> str:
    """Cryptographically random temporary password for a newly created retailer
    login. ~69 bits of entropy at the default length — not guessable from the
    shop name (replaces the old deterministic ``<username>123``)."""
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS
    ).hex()
    return secrets.compare_digest(candidate, digest)


def issue_token(db, manufacturer_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO auth_tokens (token, manufacturer_id) VALUES (?, ?)",
        (token, manufacturer_id),
    )
    return token


def issue_retailer_token(db, retailer_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO retailer_tokens (token, retailer_id) VALUES (?, ?)",
        (token, retailer_id),
    )
    return token


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.query_params.get("token")


def current_user(request: Request) -> dict:
    """Resolve the authenticated manufacturer (or super admin)."""
    token = _token_from_request(request)
    if not token:
        raise HTTPException(401, "Not authenticated")
    with get_db() as db:
        row = db.execute(
            """SELECT m.id, m.username, m.display_name, m.is_admin
               FROM auth_tokens t
               JOIN manufacturers m ON m.id = t.manufacturer_id
               WHERE t.token = ?""",
            (token,),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Invalid or expired token")
    return dict(row)


def current_manufacturer(request: Request) -> dict:
    """A regular manufacturer account (super admin owns no catalog data)."""
    user = current_user(request)
    if user["is_admin"]:
        raise HTTPException(
            403, "Super admin has no manufacturer data; log in as a manufacturer")
    return user


def current_admin(request: Request) -> dict:
    user = current_user(request)
    if not user["is_admin"]:
        raise HTTPException(403, "Super admin only")
    return user


def current_retailer(request: Request) -> dict:
    """Resolve the authenticated retailer (YourApp side)."""
    token = _token_from_request(request)
    if not token:
        raise HTTPException(401, "Not authenticated")
    with get_db() as db:
        row = db.execute(
            """SELECT r.* FROM retailer_tokens t
               JOIN retailers r ON r.id = t.retailer_id
               WHERE t.token = ?""",
            (token,),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Invalid or expired token")
    return dict(row)

"""Authentication: password hashing, bearer tokens, route dependencies.

Tokens are opaque random strings stored in the auth_tokens table. Clients
send `Authorization: Bearer <token>`; a `?token=` query parameter is also
accepted so plain links (the print-PDF tab) can authenticate.
"""

import hashlib
import secrets

from fastapi import HTTPException, Request

from .database import get_db

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS
    ).hex()
    return f"{salt}${digest}"


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

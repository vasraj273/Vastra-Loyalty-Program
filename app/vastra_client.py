"""Client for Vastra's API — Vastra is the system of record for the product
catalog and the identity provider for manufacturer logins (mobile + OTP).
This is the only place in the codebase that calls out to it.

Contract verified live against staging (2026-07-16), see
docs/integration/PRODUCT_INTEGRATION.md:

- POST /user/loyalty-signup    {country_code, mobile, is_resend} -> texts an OTP
- POST /user/loyalty-verifyotp {country_code, mobile, otp} -> org profile with
  organization_Id / organization_name / access_token
- GET  /design/get-design-ids  -> the org's designs (loyalty "products"),
  authenticated with the verify-otp access_token in the `authorization` header

Every endpoint answers 200 with an envelope:
{"status": true, "data": ...} or {"status": false, "error": {code, message}}.
"""

import os

import httpx

# Same convention as QR_BASE_URL (qr_service.py) / SSO_SECRET (auth.py):
# module-level, env-configured. Empty base URL -> feature inert (fails
# closed with VastraApiError rather than crashing on import).
# Staging base: http://13.235.138.204:3000/api/v2 (the public
# webstaging.vastraapp.com host currently 301s POSTs away and drops the path).
VASTRA_API_BASE_URL = os.environ.get("VASTRA_API_BASE_URL", "").rstrip("/")
VASTRA_API_KEY = os.environ.get("VASTRA_API_KEY", "1")  # staging value; not secret
VASTRA_API_TIMEOUT = float(os.environ.get("VASTRA_API_TIMEOUT", "10"))
# Vastra requires device headers even from a server; fixed values are accepted.
VASTRA_UDID = os.environ.get("VASTRA_UDID", "loyalty-backend")
VASTRA_DEVICE_TYPE = os.environ.get("VASTRA_DEVICE_TYPE", "android")

_NO_DESIGNS_CODE = 21014  # "Designs are not exist in organization."


class VastraApiError(Exception):
    """Transport failure or unrecognized response shape (surface as 502)."""


class VastraRejection(Exception):
    """Vastra answered but refused the request (bad OTP, unknown org, ...).
    Carries Vastra's own error code + message so the client sees the real
    reason."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _headers(access_token: str | None = None) -> dict:
    h = {
        "api-key": VASTRA_API_KEY,
        "udid": VASTRA_UDID,
        "device-type": VASTRA_DEVICE_TYPE,
    }
    if access_token:
        h["authorization"] = access_token
    return h


def _call(method: str, path: str, json: dict | None = None,
          access_token: str | None = None):
    """One Vastra call; unwraps the status/data envelope. Returns `data`."""
    if not VASTRA_API_BASE_URL:
        raise VastraApiError("VASTRA_API_BASE_URL is not configured")
    try:
        resp = httpx.request(
            method,
            f"{VASTRA_API_BASE_URL}{path}",
            json=json,
            headers=_headers(access_token),
            timeout=VASTRA_API_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise VastraApiError(str(exc)) from exc
    try:
        body = resp.json()
        status = body["status"]
    except (ValueError, KeyError, TypeError) as exc:
        raise VastraApiError(
            f"unexpected response shape (HTTP {resp.status_code})") from exc
    if not status:
        err = body.get("error") or {}
        raise VastraRejection(err.get("code"),
                              err.get("message") or "Vastra rejected the request")
    return body.get("data")


def send_login_otp(country_code: str, mobile: str, is_resend: int = 0) -> str:
    """Ask Vastra to text an OTP to the organization's registered mobile.
    Returns Vastra's confirmation message (staging echoes the OTP in it)."""
    data = _call("POST", "/user/loyalty-signup", json={
        "country_code": country_code, "mobile": mobile, "is_resend": is_resend,
    })
    return (data or {}).get("message", "OTP sent")


def verify_login_otp(country_code: str, mobile: str, otp: str) -> dict:
    """Verify the OTP; returns the org profile. Keys used downstream:
    organization_Id, organization_name, access_token."""
    data = _call("POST", "/user/loyalty-verifyotp", json={
        "country_code": country_code, "mobile": mobile, "otp": otp,
    })
    if not data or not data.get("organization_Id") or not data.get("access_token"):
        raise VastraApiError("verify-otp response missing organization_Id/access_token")
    return data


def fetch_vastra_products(access_token: str) -> list[dict]:
    """DORMANT — nothing calls this. The product catalog is CSV-imported by the
    manufacturer (see /catalog/products in app/main.py), because get-design-ids
    returns no design *name* and so could only ever supply design numbers as
    product names. Kept, not deleted: the contract below is verified against
    live staging, and reconnecting is a matter of calling this again once
    Vastra exposes names. Vastra OTP login is unaffected and still stores the
    access_token this would need.

    Returns [{"external_id": str, "name": str, "sku": str}, ...] for the
    logged-in organization, using its stored access_token.

    get-design-ids is the confirmed working list endpoint; it returns
    design_id/design_number but no design_name, so name falls back to the
    design number.
    # ponytail: swap to a names-bearing endpoint once Vastra confirms one
    """
    try:
        data = _call(
            "GET",
            "/design/get-design-ids?filterTag=0&includeNotDecidedPrice=1"
            "&maxPrice=&minPrice=&includeNotHavingTag=1&tagIds=&sortBy=1",
            access_token=access_token,
        )
    except VastraRejection as exc:
        if exc.code == _NO_DESIGNS_CODE:
            return []
        raise
    try:
        return [
            {
                "external_id": str(d["design_id"]),
                "name": d.get("design_name") or d.get("design_number")
                        or f"Design {d['design_id']}",
                "sku": d.get("design_number") or str(d["design_id"]),
            }
            for d in data
        ]
    except (KeyError, TypeError) as exc:
        raise VastraApiError(f"unexpected design list shape: {exc}") from exc

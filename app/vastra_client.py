"""Client for Vastra's product-list API — Vastra is the system of record
for the product catalog; this is the only place in the codebase that calls
out to it. The real contract (auth scheme, response shape, per-manufacturer
scoping) isn't finalized yet with the Vastra team, so the request/response
mapping below is a best-effort placeholder — see
docs/integration/PRODUCT_INTEGRATION.md for status.
"""

import os

import httpx

# Same convention as QR_BASE_URL (qr_service.py) / SSO_SECRET (auth.py):
# module-level, env-configured. Empty base URL -> feature inert (fails
# closed with VastraApiError rather than crashing on import).
VASTRA_API_BASE_URL = os.environ.get("VASTRA_API_BASE_URL", "")
VASTRA_API_KEY = os.environ.get("VASTRA_API_KEY", "")
VASTRA_API_TIMEOUT = float(os.environ.get("VASTRA_API_TIMEOUT", "5"))


class VastraApiError(Exception):
    """Vastra product-list call failed, or returned an unrecognized shape."""


def fetch_vastra_products() -> list[dict]:
    """Returns [{"external_id": str, "name": str, "sku": str}, ...].

    TBD once Vastra shares their actual contract: auth header format,
    whether the list is scoped per-manufacturer server-side or needs a
    query param, pagination, and real field names (mapped here so callers
    never see Vastra's raw response shape).
    """
    if not VASTRA_API_BASE_URL:
        raise VastraApiError("VASTRA_API_BASE_URL is not configured")
    headers = {}
    if VASTRA_API_KEY:
        headers["Authorization"] = f"Bearer {VASTRA_API_KEY}"
    try:
        resp = httpx.get(
            f"{VASTRA_API_BASE_URL}/products",
            headers=headers,
            timeout=VASTRA_API_TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise VastraApiError(str(exc)) from exc
    try:
        return [
            {"external_id": str(p["id"]), "name": p["name"], "sku": p["sku"]}
            for p in resp.json()
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise VastraApiError(f"unexpected response shape: {exc}") from exc

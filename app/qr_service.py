"""QR code generation helpers."""

import io
import os
import secrets
import uuid

import qrcode
from qrcode.image.pil import PilImage

# Base URL embedded in every QR payload. Scanning a printed code with a
# plain phone camera opens this page (the scan webview) with the token in
# the path. MUST be set to the deployed https origin before production
# printing, e.g. QR_BASE_URL=https://loyalty.yourhost.com/web/scan
QR_BASE_URL = os.environ.get(
    "QR_BASE_URL", "http://127.0.0.1:8000/web/scan")


def new_token() -> str:
    return uuid.uuid4().hex


# No 0/O/1/I — unambiguous when read off a damaged label and typed by hand.
MANUAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_manual_code() -> str:
    return "".join(secrets.choice(MANUAL_ALPHABET) for _ in range(6))


def new_reference() -> str:
    """Human-readable proof code for a gift claim, e.g. RDM-7K2QABC."""
    body = "".join(secrets.choice(MANUAL_ALPHABET) for _ in range(7))
    return f"RDM-{body}"


def payload_for(token: str) -> str:
    return f"{QR_BASE_URL}/{token}"


def render_png(token: str, box_size: int = 10) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=4,
    )
    qr.add_data(payload_for(token))
    qr.make(fit=True)
    img: PilImage = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

"""Printable PDF sheets: grid of QR codes with product label and token."""

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .qr_service import render_png

COLS = 4
ROWS = 6
PAGE_W, PAGE_H = A4
MARGIN = 12 * mm
CELL_W = (PAGE_W - 2 * MARGIN) / COLS
CELL_H = (PAGE_H - 2 * MARGIN) / ROWS
QR_SIZE = min(CELL_W, CELL_H) - 14 * mm


def build_pdf(product_name: str, sku: str,
              codes: list[tuple[str, str]]) -> bytes:
    """codes: list of (token, manual_code) pairs."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f"Loyalty QR - {product_name}")

    per_page = COLS * ROWS
    for i, (token, manual_code) in enumerate(codes):
        slot = i % per_page
        if i > 0 and slot == 0:
            pdf.showPage()
        col = slot % COLS
        row = slot // COLS

        cell_x = MARGIN + col * CELL_W
        cell_y = PAGE_H - MARGIN - (row + 1) * CELL_H

        qr_x = cell_x + (CELL_W - QR_SIZE) / 2
        qr_y = cell_y + (CELL_H - QR_SIZE) / 2 + 4 * mm
        img = ImageReader(io.BytesIO(render_png(token, box_size=6)))
        pdf.drawImage(img, qr_x, qr_y, QR_SIZE, QR_SIZE)

        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawCentredString(cell_x + CELL_W / 2, qr_y - 3 * mm,
                              f"{product_name} ({sku})")
        # Manual fallback code, large enough to read off a damaged label
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(cell_x + CELL_W / 2, qr_y - 8 * mm,
                              f"{manual_code[:3]}-{manual_code[3:]}")

    pdf.showPage()
    pdf.save()
    return buf.getvalue()

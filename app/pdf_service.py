"""Printable PDF sheets: a grid of item QR codes, plus larger box (parent)
stickers on their own page when a batch uses parent-child grouping."""

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .qr_service import render_png

PAGE_W, PAGE_H = A4
MARGIN = 12 * mm

# item sticker grid
COLS, ROWS = 4, 6
CELL_W = (PAGE_W - 2 * MARGIN) / COLS
CELL_H = (PAGE_H - 2 * MARGIN) / ROWS
QR_SIZE = min(CELL_W, CELL_H) - 14 * mm

# box (parent) sticker grid — fewer, larger. The QR is kept smaller than the
# cell so the title sits above it and the product name + code fit below it,
# all inside the border.
BCOLS, BROWS = 2, 3
BCELL_W = (PAGE_W - 2 * MARGIN) / BCOLS
BCELL_H = (PAGE_H - 2 * MARGIN) / BROWS
BQR_SIZE = min(BCELL_W, BCELL_H) - 38 * mm


def _fmt(code: str) -> str:
    return f"{code[:3]}-{code[3:]}"


def build_pdf(product_name: str, sku: str,
              codes: list[tuple]) -> bytes:
    """codes: list of (token, manual_code, items). items == 0 -> item
    sticker; items > 0 -> box (parent) sticker covering that many items."""
    children = [c for c in codes if c[2] == 0]
    parents = [c for c in codes if c[2] > 0]

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f"Loyalty QR - {product_name}")

    per_page = COLS * ROWS
    for i, (token, manual_code, _items) in enumerate(children):
        slot = i % per_page
        if i > 0 and slot == 0:
            pdf.showPage()
        col, rown = slot % COLS, slot // COLS
        cell_x = MARGIN + col * CELL_W
        cell_y = PAGE_H - MARGIN - (rown + 1) * CELL_H

        qr_x = cell_x + (CELL_W - QR_SIZE) / 2
        qr_y = cell_y + (CELL_H - QR_SIZE) / 2 + 4 * mm
        pdf.drawImage(ImageReader(io.BytesIO(render_png(token, box_size=6))),
                      qr_x, qr_y, QR_SIZE, QR_SIZE)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawCentredString(cell_x + CELL_W / 2, qr_y - 3 * mm,
                              f"{product_name} ({sku})")
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(cell_x + CELL_W / 2, qr_y - 8 * mm,
                              _fmt(manual_code))

    if parents:
        if children:
            pdf.showPage()
        per_page = BCOLS * BROWS
        for i, (token, manual_code, items) in enumerate(parents):
            slot = i % per_page
            if i > 0 and slot == 0:
                pdf.showPage()
            col, rown = slot % BCOLS, slot // BCOLS
            cell_x = MARGIN + col * BCELL_W
            cell_y = PAGE_H - MARGIN - (rown + 1) * BCELL_H
            cx = cell_x + BCELL_W / 2

            # border so a box sticker is unmistakable on the carton
            inner_x, inner_y = cell_x + 5 * mm, cell_y + 5 * mm
            pdf.setLineWidth(1.2)
            pdf.rect(inner_x, inner_y, BCELL_W - 10 * mm, BCELL_H - 10 * mm)

            # Title sits just below the top border.
            pdf.setFont("Helvetica-Bold", 13)
            pdf.drawCentredString(cx, cell_y + BCELL_H - 14 * mm,
                                  f"BOX — {items} items")

            # QR shifted up so both labels fit below it, above the bottom line.
            qr_x = cx - BQR_SIZE / 2
            qr_y = inner_y + 17 * mm
            pdf.drawImage(
                ImageReader(io.BytesIO(render_png(token, box_size=8))),
                qr_x, qr_y, BQR_SIZE, BQR_SIZE)

            # Product name then manual code, both inside the border.
            pdf.setFont("Helvetica-Bold", 8)
            pdf.drawCentredString(cx, inner_y + 9 * mm,
                                  f"{product_name} ({sku})")
            pdf.setFont("Helvetica-Bold", 12)
            pdf.drawCentredString(cx, inner_y + 3 * mm, _fmt(manual_code))

    pdf.showPage()
    pdf.save()
    return buf.getvalue()

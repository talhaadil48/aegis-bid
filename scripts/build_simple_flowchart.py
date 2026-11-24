"""Render the simple AegisBid demo flowchart as a PNG."""

from io import BytesIO
from pathlib import Path

from pypdfium2 import PdfDocument
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/submission/AegisBid_Simple_Flowchart.png"
WIDTH, HEIGHT = 1600, 900
MARGIN, GAP = 54, 39
CARD_WIDTH = (WIDTH - 2 * MARGIN - 5 * GAP) / 6
CARD_HEIGHT = 122
BACKGROUND = HexColor("#F7FAFC")
INK = HexColor("#142B3D")
MUTED = HexColor("#496274")
TEAL = HexColor("#0B7162")
TEAL_LINE = HexColor("#A7D0C5")
BLUE_LINE = HexColor("#B9CDD9")
WHITE = HexColor("#FFFFFF")
MINT = HexColor("#EAF6F0")


def x_position(index):
    return MARGIN + index * (CARD_WIDTH + GAP)


def label(page, x, y, text, size, color=INK, *, bold=False, center=False):
    page.setFillColor(color)
    page.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    draw = page.drawCentredString if center else page.drawString
    draw(x, HEIGHT - y, text)


def card(page, index, top, title, detail, *, green=False):
    x = x_position(index)
    page.setFillColor(MINT if green else WHITE)
    page.setStrokeColor(TEAL_LINE if green else BLUE_LINE)
    page.setLineWidth(1.7)
    page.roundRect(x, HEIGHT - top - CARD_HEIGHT, CARD_WIDTH, CARD_HEIGHT, 14, stroke=1, fill=1)
    middle = x + CARD_WIDTH / 2
    label(page, middle, top + 51, title, 26, bold=True, center=True)
    label(page, middle, top + 82, detail, 18, MUTED, center=True)


def arrow(page, start, end, color):
    sx, sy = start
    ex, ey = end
    page.setStrokeColor(color)
    page.setLineWidth(2.6)
    page.line(sx, HEIGHT - sy, ex, HEIGHT - ey)
    if sy == ey:
        page.line(ex, HEIGHT - ey, ex - 8, HEIGHT - ey + 6)
        page.line(ex, HEIGHT - ey, ex - 8, HEIGHT - ey - 6)
    else:
        page.line(ex, HEIGHT - ey, ex - 6, HEIGHT - ey + 8)
        page.line(ex, HEIGHT - ey, ex + 6, HEIGHT - ey + 8)


def row(page, start_index, top, cards, color, green_indices):
    for index, (title, detail) in enumerate(cards, start=start_index):
        card(page, index, top, title, detail, green=index in green_indices)
        if index < start_index + len(cards) - 1:
            y = top + CARD_HEIGHT / 2
            arrow(page, (x_position(index) + CARD_WIDTH + 6, y), (x_position(index + 1) - 6, y), color)


def main():
    pdf_bytes = BytesIO()
    page = canvas.Canvas(pdf_bytes, pagesize=(WIDTH, HEIGHT))
    page.setFillColor(BACKGROUND)
    page.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)

    label(page, MARGIN, 112, "AegisBid system flow", 68, bold=True)
    page.setStrokeColor(BLUE_LINE)
    page.setLineWidth(1.5)
    page.line(MARGIN, HEIGHT - 156, WIDTH - MARGIN, HEIGHT - 156)
    label(page, MARGIN, 248, "BIDDING", 23, TEAL, bold=True)
    row(
        page,
        0,
        283,
        [
            ("Seller", "Lists an auction"),
            ("Bidder", "Places a bid"),
            ("Bid intake", "Nginx · Go · FastAPI"),
            ("PostgreSQL", "Saves and orders bids"),
            ("Worker", "Accepts or rejects"),
            ("Dashboard", "Live price and winners"),
        ],
        MUTED,
        {3},
    )

    database_x = x_position(3) + CARD_WIDTH / 2
    arrow(page, (database_x, 414), (database_x, 573), TEAL)
    label(page, database_x + 23, 520, "BACKUP AND RESTORE", 22, TEAL, bold=True)
    row(
        page,
        3,
        582,
        [
            ("Database export", "Saved snapshot"),
            ("Bacula backup", "Stores the files"),
            ("Verified restore", "Checks bids and winners"),
        ],
        TEAL,
        {3, 4, 5},
    )
    page.save()

    pdf = PdfDocument(pdf_bytes.getvalue())
    diagram = pdf[0]
    bitmap = diagram.render(scale=1.2)
    bitmap.to_pil().copy().save(OUTPUT)
    bitmap.close()
    diagram.close()
    pdf.close()
    print(OUTPUT)


if __name__ == "__main__":
    main()

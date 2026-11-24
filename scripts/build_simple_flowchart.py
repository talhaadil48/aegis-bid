"""Render the AegisBid demo flowchart as a presentation-ready PNG."""

from io import BytesIO
from math import hypot
from pathlib import Path

from pypdfium2 import PdfDocument
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/submission/AegisBid_Technology_Flowchart.png"
WIDTH, HEIGHT = 1600, 900
MARGIN, GAP = 54, 46
CARD_WIDTH = (WIDTH - 2 * MARGIN - 4 * GAP) / 5
CARD_HEIGHT = 120
BACKGROUND = HexColor("#F5F8FC")
INK = HexColor("#11243A")
MUTED = HexColor("#465C70")
BLUE = HexColor("#25548B")
BLUE_LINE = HexColor("#BCCDE1")
BLUE_FILL = HexColor("#EBF2FC")
TEAL = HexColor("#07695A")
TEAL_LINE = HexColor("#A7D0C5")
TEAL_FILL = HexColor("#E6F3EE")
WHITE = HexColor("#FFFFFF")

INTAKE = [
    ("Auction website", "Next.js · React", "List an item or place a bid"),
    ("Traffic routing", "Nginx", "Routes requests to services"),
    ("Bid intake", "Go", "Groups bids for one auction"),
    ("Request validation", "FastAPI · Python", "Checks the account and bid"),
    ("Durable queue", "PostgreSQL", "Saves and orders bids"),
]

DECISIONS = [
    ("Role dashboards", "Next.js · React", "Show bid results and winners"),
    ("Live gateway", "Go · WebSockets", "Reads and shares prices"),
    ("Auction ledger", "PostgreSQL", "Saves decisions and winners"),
    ("Bid decisions", "Python worker", "Reads queued bids in order"),
    ("Message journal", "NATS JetStream", "Delivers bid notifications"),
]

RECOVERY = [
    ("Consistent export", "pg_dump · SHA-256", "Saves a dump and checksum"),
    ("Backup jobs", "Bacula", "Stores and retrieves files"),
    ("Restore and verify", "pg_restore · Python", "Checks bids and winners"),
]


def x_position(index):
    return MARGIN + index * (CARD_WIDTH + GAP)


def text(page, x, y, value, size, color=INK, *, bold=False, right=False):
    page.setFillColor(color)
    page.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    draw = page.drawRightString if right else page.drawString
    draw(x, HEIGHT - y, value)


def box(page, x, top, width, height, fill, stroke=None, corners=12):
    page.setFillColor(fill)
    if stroke:
        page.setStrokeColor(stroke)
    page.setLineWidth(1.5)
    page.roundRect(x, HEIGHT - top - height, width, height, corners, stroke=bool(stroke), fill=1)


def card(page, index, top, labels, *, recovery=False, emphasized=False):
    x = x_position(index)
    accent, border, tint = (TEAL, TEAL_LINE, TEAL_FILL) if recovery else (BLUE, BLUE_LINE, BLUE_FILL)
    box(page, x, top, CARD_WIDTH, CARD_HEIGHT, tint if emphasized else WHITE, border)
    title, technology, detail = labels
    text(page, x + 15, top + 32, title, 24, bold=True)
    text(page, x + 15, top + 63, technology, 19, accent, bold=True)
    text(page, x + 15, top + 94, detail, 16.5, MUTED)


def arrow(page, start, end, color):
    sx, sy = start
    ex, ey = end
    length = hypot(ex - sx, ey - sy)
    dx, dy = (ex - sx) / length, (ey - sy) / length
    page.setStrokeColor(color)
    page.setLineWidth(2.8)
    page.setLineCap(1)
    page.line(sx, HEIGHT - sy, ex, HEIGHT - ey)
    for side in (-1, 1):
        x = ex - 9 * dx - side * 5 * dy
        y = ey - 9 * dy + side * 5 * dx
        page.line(ex, HEIGHT - ey, x, HEIGHT - y)


def sql_fallback(page, queue_x, worker_x):
    page.saveState()
    page.setStrokeColor(MUTED)
    page.setLineWidth(2)
    page.setDash(7, 6)
    source_x = queue_x - 43
    page.line(source_x, HEIGHT - 301, source_x, HEIGHT - 328)
    page.line(source_x, HEIGHT - 328, worker_x, HEIGHT - 328)
    page.line(worker_x, HEIGHT - 328, worker_x, HEIGHT - 382)
    page.restoreState()
    arrow(page, (worker_x, 382), (worker_x, 395), MUTED)
    text(page, worker_x + 12, 354, "SQL fallback", 16, MUTED)


def row(page, offset, top, cards, *, reverse=False, recovery=False, highlighted=()):
    for index, labels in enumerate(cards, start=offset):
        card(page, index, top, labels, recovery=recovery, emphasized=index in highlighted)
        if index < offset + len(cards) - 1:
            y = top + CARD_HEIGHT / 2
            left = (x_position(index) + CARD_WIDTH + 7, y)
            right = (x_position(index + 1) - 7, y)
            start, end = (right, left) if reverse else (left, right)
            arrow(page, start, end, TEAL if recovery else BLUE)


def main():
    pdf_bytes = BytesIO()
    page = canvas.Canvas(pdf_bytes, pagesize=(WIDTH, HEIGHT))
    page.setFillColor(BACKGROUND)
    page.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)
    page.setFillColor(INK)
    page.rect(0, HEIGHT - 112, WIDTH, 112, fill=1, stroke=0)
    text(page, MARGIN, 72, "AegisBid system flow", 53, WHITE, bold=True)

    text(page, MARGIN, 155, "01  RECEIVE THE BID", 20, BLUE, bold=True)
    row(page, 0, 174, INTAKE, highlighted=(4,))

    queue_x = x_position(4) + CARD_WIDTH / 2
    arrow(page, (queue_x, 301), (queue_x, 395), BLUE)
    text(page, queue_x - 15, 378, "Python relay", 16, MUTED, right=True)
    sql_fallback(page, queue_x, x_position(3) + CARD_WIDTH / 2)
    text(page, MARGIN, 379, "02  DECIDE AND UPDATE", 20, BLUE, bold=True)
    row(page, 0, 404, DECISIONS, reverse=True, highlighted=(2,))

    ledger_x = x_position(2) + CARD_WIDTH / 2
    arrow(page, (ledger_x, 531), (ledger_x, 616), TEAL)
    text(page, MARGIN, 657, "03  BACK UP AND VERIFY", 20, TEAL, bold=True)
    row(page, 2, 625, RECOVERY, recovery=True, highlighted=(2, 3, 4))

    box(page, MARGIN, 793, WIDTH - 2 * MARGIN, 64, WHITE, BLUE_LINE)
    text(page, MARGIN + 17, 832, "OTHER RECOVERY PATHS", 17, TEAL, bold=True)
    text(page, 375, 832, "CloudNativePG · Standby failover", 17, MUTED)
    text(page, 772, 832, "PostgreSQL WAL · Point-in-time restore", 17, MUTED)
    text(page, 1220, 832, "AWS S3 · Encrypted backup", 17, MUTED)
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

"""Publication-sized vector system diagram with a single readable bid spine."""

from itertools import pairwise

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth

INK = colors.HexColor("#172B45")
MUTED = colors.HexColor("#56677C")
EDGE = colors.HexColor("#DCE3EB")
BLUE = colors.HexColor("#3666AA")
TEAL = colors.HexColor("#15746B")
PURPLE = colors.HexColor("#7456A0")
AMBER = colors.HexColor("#A77831")
WHITE = colors.white


def system_design(width=511):
    """Coordinates use a 520 x 650 page, with y measured from the top."""
    height = 650
    drawing = Drawing(width, height * width / 520)

    def text(x, top, value, size=8.3, bold=False, color=MUTED, anchor="start"):
        drawing.add(
            String(
                x,
                height - top,
                value,
                fontName="Helvetica-Bold" if bold else "Helvetica",
                fontSize=size,
                fillColor=color,
                textAnchor=anchor,
            )
        )

    def rect(x, top, w, h, fill=WHITE, border=EDGE, radius=6):
        drawing.add(
            Rect(x, height - top - h, w, h, rx=radius, ry=radius, fillColor=fill, strokeColor=border, strokeWidth=0.65)
        )

    def line(points, color=BLUE, dashed=False, head=True):
        for (x1, y1), (x2, y2) in pairwise(points):
            segment = Line(x1, height - y1, x2, height - y2, strokeColor=color, strokeWidth=0.9)
            if dashed:
                segment.strokeDashArray = [3, 3]
            drawing.add(segment)
        if head:
            (ax, ay), (bx, by) = points[-2:]
            if bx == ax:
                direction = 1 if by > ay else -1
                vertices = [
                    bx,
                    height - by,
                    bx - 2.7,
                    height - by + direction * 4.5,
                    bx + 2.7,
                    height - by + direction * 4.5,
                ]
            else:
                direction = 1 if bx > ax else -1
                vertices = [
                    bx,
                    height - by,
                    bx - direction * 4.5,
                    height - by - 2.7,
                    bx - direction * 4.5,
                    height - by + 2.7,
                ]
            drawing.add(Polygon(vertices, fillColor=color, strokeColor=color, strokeWidth=0.4))

    def section(top, number, title, color=BLUE):
        text(20, top, number, 8, True, color)
        text(43, top, title, 8, True, INK)

    def card(x, top, w, h, title, lines, accent=BLUE, fill=WHITE):
        rect(x, top, w, h, fill)
        drawing.add(Line(x + 12, height - top - 14, x + 12, height - top - 27, strokeColor=accent, strokeWidth=2.5))
        text(x + 22, top + 23, title, 10, True, INK)
        if stringWidth(title, "Helvetica-Bold", 10) > w - 34:
            raise ValueError(f"Diagram card title overflows: {title}")
        for index, value in enumerate(lines):
            if stringWidth(value, "Helvetica", 8.2) > w - 24:
                raise ValueError(f"Diagram card text overflows: {value}")
            text(x + 12, top + 39 + index * 11.5, value, 8.2)

    section(10, "01", "ACCESS & IDENTITY")
    for x, label in zip([20, 143, 266, 389], ["Bidder", "Seller", "Administrator", "Auditor"], strict=True):
        rect(x, 22, 111, 22, fill=colors.HexColor("#F3F6FA"), border=colors.HexColor("#F3F6FA"))
        text(x + 55.5, 36.5, label, 8.6, True, INK, "middle")
        line([(x + 55.5, 44), (x + 55.5, 51)], head=False)
    card(20, 58, 218, 62, "Web application", ["Next.js role views + Nginx proxy", "Session cookie / HTTP / WebSocket"])
    card(282, 58, 218, 62, "Go intake + FastAPI", ["Separate bid ingress / real session checks", "Bounded batches / UUID / integer cents"])
    line([(75.5, 51), (444.5, 51)], head=False)
    line([(129, 51), (129, 58)])
    line([(238, 89), (282, 89)])

    section(140, "02", "DURABLE BID PROCESSING")
    line([(429, 175), (429, 159), (91, 159), (91, 175)], dashed=True)
    rect(178, 150, 164, 15, border=WHITE, radius=0)
    text(260, 160, "Worker also reconciles SQL intake", 7.8, color=BLUE, anchor="middle")
    card(358, 175, 142, 63, "SQL intake", ["Parallel sequence reservation", "Commit -> 202 QUEUED"])
    card(189, 175, 142, 63, "JetStream", ["Relay -> durable command", "Same UUID / retry + ACK"])
    card(20, 175, 142, 63, "Auction worker", ["Prefix barrier + lease epoch", "Price / cutoff / intake order"])
    line([(475, 120), (475, 175)])
    line([(358, 206), (331, 206)])
    line([(189, 206), (162, 206)])
    rect(189, 242, 311, 15, fill=colors.HexColor("#F3F6FA"), border=colors.HexColor("#F3F6FA"), radius=3)
    text(344.5, 252, "Late UUID -> CLOSED receipt; sealed result unchanged", 7.7, color=INK, anchor="middle")
    line([(500, 206), (510, 206), (510, 249.5), (500, 249.5)])
    line([(91, 238), (91, 260)])
    text(100, 252, "commit", 7.5)

    rect(20, 260, 480, 65, fill=INK, border=INK)
    text(35, 281, "PostgreSQL  /  one atomic ordered batch", 11, True, WHITE)
    text(35, 298, "Separate bid results + hash events; offers + states + latest-version outbox", 9, color=WHITE)
    text(
        35,
        313,
        "At close: drain intake -> rank distinct bidders -> allocate stock",
        8.5,
        color=colors.HexColor("#CBDAEC"),
    )

    section(349, "03", "COMMITTED OUTPUTS")
    line([(260, 325), (260, 357)], head=False)
    line([(91, 357), (429, 357)], head=False)
    for x in [91, 260, 429]:
        line([(x, 357), (x, 369)])
    card(
        20,
        369,
        142,
        76,
        "Live updates",
        ["Separate Go fanout service", "API snapshots: 2 s scale tick", "One-slot queue -> role views"],
        accent=TEAL,
    )
    card(
        189,
        369,
        142,
        76,
        "Audit & replay",
        ["SHA-256 event chain", "Optional Ed25519 signature", "Rules + winners verified"],
        accent=PURPLE,
    )
    card(
        358,
        369,
        142,
        76,
        "Notifications",
        ["SQL outbox -> relay", "NATS live subjects + retries", "Go uses the API read path"],
    )

    section(469, "04", "BACKUP & VERIFIED RECOVERY", TEAL)
    line([(500, 292), (510, 292), (510, 477), (91, 477)], color=AMBER, head=False)
    for x in [91, 260, 429]:
        line([(x, 477), (x, 489)], color=AMBER)
    card(20, 489, 142, 63, "Bacula", ["pg_dump + file checksums", "Director / FD / SD / Catalog"], accent=TEAL)
    card(
        189, 489, 142, 63, "Physical PITR", ["Base backup + archived WAL", "Named / time recovery target"], accent=TEAL
    )
    card(358, 489, 142, 63, "S3 vault", ["AES-GCM + exact versions", "COMPLIANCE retention"], accent=TEAL)
    for x in [91, 260, 429]:
        line([(x, 552), (x, 561)], color=TEAL, head=False)
    line([(91, 561), (429, 561)], color=TEAL, head=False)
    line([(260, 561), (260, 572)], color=TEAL)
    rect(20, 572, 480, 25, fill=colors.HexColor("#ECF6F2"), border=colors.HexColor("#ECF6F2"))
    text(
        260,
        588.5,
        "Isolated restore   ->   verify ledger + winners   ->   recovery certificate",
        8.7,
        True,
        TEAL,
        "middle",
    )

    section(618, "05", "PLATFORM & OPERATIONS")
    text(20, 634, "Observe: Prometheus / Grafana    |    Control: admin metrics + allowlisted local chaos", 8)
    text(
        20,
        648,
        "HA: local failover tested    |    Target: 3-zone EKS, CNPG + NATS    |    Real zone proof pending",
        7.9,
    )
    drawing.scale(width / 520, width / 520)
    return drawing

"""Vector system design shared by the report PDF, standalone SVG and Word image."""

from itertools import pairwise

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors

NAVY = colors.HexColor("#16334D")
TEAL = colors.HexColor("#126C78")
BLUE = colors.HexColor("#EAF3F5")
GOLD = colors.HexColor("#FFF4D9")


def system_design(width=511):
    drawing = Drawing(width, 650 * width / 529)

    def text(x, y, value, size=8, bold=False, color=NAVY, anchor="middle"):
        drawing.add(
            String(
                x,
                y,
                value,
                fontName="Helvetica-Bold" if bold else "Helvetica",
                fontSize=size,
                fillColor=color,
                textAnchor=anchor,
            )
        )

    def box(x, y, w, h, title, lines, fill=BLUE):
        drawing.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=fill, strokeColor=TEAL, strokeWidth=0.8))
        text(x + w / 2, y + h - 13, title, 8.5, True)
        for index, value in enumerate(lines):
            text(x + w / 2, y + h - 25 - index * 10, value, 7.7)

    def arrow(points, color=TEAL, dashed=False):
        for a, b in pairwise(points):
            line = Line(*a, *b, strokeColor=color, strokeWidth=0.9)
            if dashed:
                line.strokeDashArray = [3, 2]
            drawing.add(line)
        (ax, ay), (bx, by) = points[-2:]
        if bx == ax:
            sign = 1 if by > ay else -1
            vertices = [bx, by, bx - 3, by - sign * 5, bx + 3, by - sign * 5]
        else:
            sign = 1 if bx > ax else -1
            vertices = [bx, by, bx - sign * 5, by - 3, bx - sign * 5, by + 3]
        drawing.add(Polygon(vertices, fillColor=color, strokeColor=color))

    for x, title, lines in [
        (28, "Bidder", ["Bid / history / winners"]),
        (149, "Seller", ["Create / schedule / close"]),
        (270, "Administrator", ["Metrics / incidents"]),
        (391, "Auditor", ["Export / independent replay"]),
    ]:
        box(x, 601, 110, 38, title, lines)
        arrow([(x + 55, 601), (x + 55, 581)])

    box(
        28,
        544,
        473,
        37,
        "Next.js role views + Nginx same-origin boundary",
        ["HTTPS in production | HTTP / WebSocket proxy | session cookie | reconnect + version refresh"],
    )
    arrow([(178, 544), (178, 519)])
    text(185, 529, "authenticated HTTP", 7, anchor="start")
    box(
        28,
        472,
        300,
        47,
        "FastAPI: authenticate + authorize + validate",
        [
            "scrypt / HS256 | RBAC / owner checks | origin + limits",
            "bidder identity from session; UUID + integer cents",
        ],
    )
    box(351, 472, 150, 47, "Operations", ["Prometheus / Grafana", "admin-only local chaos"])
    arrow([(328, 495), (351, 495)], dashed=True)
    arrow([(133, 472), (133, 446)])
    text(141, 456, "POST bid", 7, anchor="start")

    box(
        28,
        399,
        210,
        47,
        "1. Durable SQL intake",
        ["UUID + immutable payload; admission time + seq", "COMMIT -> HTTP 202 QUEUED; retry reuses row"],
    )
    box(
        291,
        399,
        210,
        47,
        "2. NATS JetStream journal",
        ["relay publishes Nats-Msg-Id = request UUID", "file-backed stream; retries; explicit consumer ACK"],
    )
    arrow([(238, 422), (291, 422)])
    text(264, 430, "relay", 7)
    arrow([(133, 399), (133, 375)])
    text(143, 382, "SQL reconcile", 7, anchor="start")
    arrow([(396, 399), (396, 387), (133, 387), (133, 375)])
    text(305, 379, "command delivery / redelivery", 7)
    box(
        28,
        326,
        210,
        49,
        "3. Worker: serialize one auction",
        ["lock auction, then 5 s lease; verify holder / epoch", "first QUEUED intake_seq; price + deadline rules"],
    )
    box(
        291,
        326,
        210,
        49,
        "4. One SQL transaction",
        ["decision + offer + request + event + outbox", "COMMIT before ACK; retry has one business effect"],
    )
    arrow([(238, 350), (291, 350)])
    text(264, 358, "decide", 7)
    arrow([(396, 326), (396, 301)])

    box(
        28,
        250,
        473,
        51,
        "PostgreSQL: authoritative durable state",
        [
            "users | auctions | intake | fenced leases | decisions | offers | winners | chained events | outbox",
            "Deadline close: drain eligible intake -> rank distinct offers -> stock-limited allocation + close event",
        ],
        fill=colors.HexColor("#DAEBEE"),
    )
    for x in [100, 263, 427]:
        arrow([(x, 250), (x, 223)])
    text(263, 235, "committed read models / event export", 7)
    box(
        28,
        159,
        145,
        64,
        "Realtime read path",
        [
            "authenticated snapshot API",
            "Go hub polls 1 s / auction",
            "prepared frames; one-slot queue",
            "WebSocket fanout to clients",
        ],
    )
    box(
        191,
        159,
        145,
        64,
        "Independent audit",
        [
            "SHA-256 canonical event chain",
            "optional Ed25519 manifest",
            "replay prices / cutoff / winners",
            "trusted key: PASS / FAIL",
        ],
    )
    box(
        354,
        159,
        147,
        64,
        "Notification outbox",
        [
            "relay publishes live subjects",
            "SQL marks published / retries",
            "Go gateway currently polls API",
            "not this NATS live subject",
        ],
    )
    arrow([(28, 191), (10, 191), (10, 562), (28, 562)])
    text(14, 533, "WS", 7, anchor="start")
    text(263, 146, "Unsigned export: INCOMPLETE | owner receipt: event/hash reference", 7)

    # The recovery bus branches from the database independently of realtime/audit delivery.
    arrow([(501, 276), (518, 276), (518, 136), (420, 136), (420, 133)], color=colors.HexColor("#9C6716"))
    box(28, 68, 473, 65, "Backup, recovery and integrity verification", [], fill=GOLD)
    for x in [185.5, 343]:
        drawing.add(Line(x, 72, x, 113, strokeColor=colors.HexColor("#D8BC7C"), strokeWidth=0.6))
    for x, title, lines in [
        (
            107,
            "Logical / Bacula",
            ["consistent pg_dump + checksums", "Director / FD / SD + Catalog", "alternate restore; replay verifier"],
        ),
        (
            264,
            "Physical / continuous WAL",
            ["pg_basebackup + pg_verifybackup", "archive WAL; named/time target", "isolated PITR + ledger anchor"],
        ),
        (
            422,
            "Remote S3 vault",
            ["AES-GCM + exact VersionIds", "COMPLIANCE retention + key custody", "decrypt -> isolated DB -> verify"],
        ),
    ]:
        text(x, 108, title, 8, True)
        for index, value in enumerate(lines):
            text(x, 96 - index * 10, value, 7.2)
    text(
        264,
        54,
        "Restore is isolated; verification and measured recovery certificate precede any production cutover.",
        7,
    )
    box(
        28,
        0,
        473,
        43,
        "HA / deployment boundary",
        [
            "Local proof: kind node loss + synchronous PostgreSQL promotion; three-replica NATS TLS/quorum",
            "Production templates: 3-zone EKS, CNPG, spread/HPA, remote Barman WAL; real zone/PITR RPO proof pending",
        ],
        fill=colors.HexColor("#F1F3F7"),
    )
    drawing.scale(width / 529, width / 529)
    return drawing

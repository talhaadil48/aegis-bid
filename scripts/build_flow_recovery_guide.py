"""Build the plain English AegisBid system and recovery walkthrough."""

from pathlib import Path

from pypdf import PdfReader
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/submission/AegisBid_Flow_and_Recovery_Guide.pdf"
NAVY = HexColor("#122840")
TEAL = HexColor("#08665F")
TEXT = HexColor("#243C50")
LINE = HexColor("#C8D7DE")
PALE = HexColor("#F1F6F8")
MINT = HexColor("#E7F4EF")
MARGIN = 45
WIDTH = A4[0] - 2 * MARGIN - 12

STYLES = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=28, leading=32, textColor=NAVY, spaceAfter=9),
    "lead": ParagraphStyle("lead", fontName="Helvetica", fontSize=14, leading=20, textColor=TEXT, spaceAfter=17),
    "heading": ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=TEAL, spaceBefore=11, spaceAfter=6),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=12, leading=17, textColor=TEXT, spaceAfter=8, alignment=TA_LEFT),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=11.5, leading=15, textColor=TEXT),
    "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=white),
    "note": ParagraphStyle("note", fontName="Helvetica", fontSize=10, leading=14, textColor=TEXT, spaceBefore=9),
}


def p(text, style="body"):
    return Paragraph(text, STYLES[style])


def start(title, lead):
    return [p(title, "title"), p(lead, "lead")]


def hint(text):
    box = Table([[p("<b>Show in your demo.</b> " + text, "cell")]], colWidths=[WIDTH])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), MINT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return [Spacer(1, 11), box]


def table(headers, rows, fractions):
    cells = [[p(header, "label") for header in headers]]
    cells.extend([p(text, "cell") for text in row] for row in rows)
    grid = Table(cells, colWidths=[WIDTH * fraction for fraction in fractions])
    grid.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PALE, white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.45, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return grid


def node(drawing, x, y, width, title, subtitle, highlighted=False):
    drawing.add(Rect(x, y, width, 51, rx=7, ry=7, fillColor=MINT if highlighted else PALE, strokeColor=LINE))
    drawing.add(String(x + width / 2, y + 30, title, fontName="Helvetica-Bold", fontSize=11, textAnchor="middle", fillColor=NAVY))
    drawing.add(String(x + width / 2, y + 14, subtitle, fontName="Helvetica", fontSize=9, textAnchor="middle", fillColor=TEXT))


def arrow(drawing, start_x, end_x, y):
    drawing.add(Line(start_x, y, end_x - 6, y, strokeColor=TEAL, strokeWidth=1.5))
    drawing.add(Polygon([end_x, y, end_x - 6, y - 3.5, end_x - 6, y + 3.5], fillColor=TEAL, strokeColor=None))


def bid_diagram():
    drawing = Drawing(WIDTH, 70)
    labels = [
        ("Browser", "Sends a bid"),
        ("Nginx", "Routes traffic"),
        ("Go + FastAPI", "Group and check"),
        ("PostgreSQL", "Saves and orders"),
        ("Worker", "Decides the bid"),
    ]
    gap = 18
    size = (WIDTH - 4 * gap) / 5
    for i, (title, detail) in enumerate(labels):
        x = i * (size + gap)
        node(drawing, x, 11, size, title, detail, highlighted=i == 3)
        if i < len(labels) - 1:
            arrow(drawing, x + size + 2, x + size + gap - 2, 36)
    return drawing


def replication_diagram():
    drawing = Drawing(WIDTH, 128)
    x = WIDTH - 145
    node(drawing, 1, 42, 155, "Primary · Zone A", "Only writer", highlighted=True)
    node(drawing, x, 72, 144, "Standby · Zone B", "Receives and replays WAL")
    node(drawing, x, 9, 144, "Standby · Zone C", "Receives and replays WAL")
    mid = (156 + x) / 2
    drawing.add(Line(158, 67, mid, 67, strokeColor=TEAL, strokeWidth=1.5))
    drawing.add(Line(mid, 34, mid, 97, strokeColor=TEAL, strokeWidth=1.5))
    arrow(drawing, mid, x - 2, 97)
    arrow(drawing, mid, x - 2, 34)
    drawing.add(String(mid + 8, 64, "WAL stream", fontName="Helvetica-Bold", fontSize=10, fillColor=TEAL))
    return drawing


def page_content():
    return [
        [
            *start("From bid to winner", "Follow one auction for one keyboard. It starts at <b>$100</b> and each new high bid must beat the last by at least <b>$5</b>."),
            bid_diagram(),
            p("1. The seller publishes the auction", "heading"),
            p("In <b>Seller studio</b>, the seller adds the title, number of units, opening time, and deadline. The listing appears in the shared marketplace. The seller also sees it in <b>My auctions</b>."),
            p("2. The bidder sends a price", "heading"),
            p("Nginx sends the request to Go. Go can group up to 512 bids per auction in one trip. FastAPI checks the login, bidder role, amount, and request ID. PostgreSQL gives each request a position and saves it. <b>Queued</b> means the bid has been saved and is waiting for a decision."),
            p("3. The worker checks the offers in order", "heading"),
            p("The first $100 bid can be accepted. Another $100 bid then falls below the new $105 minimum. Different auctions can be checked in parallel. For one auction, a single worker decides the saved requests in order."),
            p("4. The deadline arrives and the app picks the winner", "heading"),
            p("The worker finishes bids admitted before the deadline. The highest eligible bidder wins. If $105 was highest, that bidder pays $105. After the decision, the buyer sees <b>Final allocation</b>. The audit records how the result was reached."),
            *hint("Create an auction as a seller. In a second window, bid as a bidder. Return to <b>Latest bids</b> to show the amount, decision, and reason."),
        ],
        [
            *start("When something fails", "The saved database record lets the app resume when a browser, worker, or service goes down."),
            table(
                ["Failure", "What AegisBid does"],
                [
                    ["<b>The reply is lost</b>", "Retry using the same request ID. If the bid was already saved, the app finds the original request and returns its result. The bid has one effect."],
                    ["<b>The worker crashes</b>", "An unfinished database transaction rolls back. Saved bids stay queued. After the worker's time limit expires, another worker can take over. The database blocks writes using an older worker's permission."],
                    ["<b>NATS is interrupted</b>", "NATS carries messages to tell services about work. A running worker can find pending bids directly in PostgreSQL. The relay can send saved messages when NATS returns. Worker startup still needs NATS."],
                    ["<b>The live feed drops</b>", "The browser reconnects and gets the latest price. The Go gateway shares one price snapshot across viewers. The bidder can check the saved result in <b>Your bid history</b>."],
                    ["<b>Too many requests arrive</b>", "Go limits how much work waits in memory. A full buffer can return <b>429</b>. If the reply is uncertain, retry with the original request ID while the auction still accepts new bids."],
                    ["<b>The deadline passes</b>", "New late bids get <b>Closed</b>. The worker finishes eligible queued bids before choosing the winners. Late requests leave the finished auction result intact."],
                ],
                [0.29, 0.71],
            ),
            p("Why separate the traffic? Why no Redis?", "heading"),
            p("Nginx sends bids to Go intake and live viewers to a separate Go gateway. In production, a load balancer and Kubernetes would distribute requests across healthy app instances. PostgreSQL holds the official bid record, NATS delivers messages, and Go shares live prices. A Redis cache could speed up reads later. Bid decisions would still use PostgreSQL."),
            *hint("Show <b>Queued</b> and <b>Worker leadership</b> in Admin. Explain that another worker can continue from saved bids."),
        ],
        [
            *start("How PostgreSQL stays in sync", "The production design places one primary and two standby copies in three separate cloud zones. Each auction has one place where writes are accepted."),
            replication_diagram(),
            p("1. The primary records each change", "heading"),
            p("When a bid is saved, the primary writes the change to its <b>write-ahead log</b>, or <b>WAL</b>. Think of WAL as PostgreSQL's record of the changes it needs to recover. A new standby starts with a copy of the database, then receives and replays these records to catch up."),
            p("2. A standby confirms the write", "heading"),
            p("Both standbys receive the stream. The configuration uses <b>ANY 1</b>. A write can be confirmed after the primary and at least one standby have written the relevant WAL safely to disk. The other standby can be behind and catch up. With no eligible standby to acknowledge, the required synchronous configuration can make writes wait."),
            p("3. If the primary fails, one standby takes over", "heading"),
            p("CloudNativePG checks which standby can take over safely and whether it has enough information to confirm that choice. It isolates the old primary and promotes the eligible standby. The app reconnects through the same database service, <b>aegis-pg-rw</b>, which now points to the new primary. Uncertain bid requests can be retried with their original IDs."),
            p("What we proved locally", "heading"),
            p("A lab drill stopped the node hosting the primary. Promotion and checks took <b>67.21 seconds</b> and preserved <b>three committed decisions</b>. The lab ran on one host. The design for physical AWS zones has yet to be launched."),
            *hint("Point to the two WAL arrows. Say, “One database writes. The standbys copy its changes. If the writer fails, one safe copy becomes the writer.”"),
        ],
        [
            *start("How recovery actually works", "Choose the recovery method that matches what was lost."),
            table(
                ["Mechanism", "When you use it", "What it does"],
                [
                    ["<b>PostgreSQL standby failover</b>", "The primary database server stops.", "An eligible standby becomes the new primary after safety checks. The local drill took about 67 seconds, including verification, and kept all three committed decisions in that drill."],
                    ["<b>Bacula backup and restore</b>", "You need a saved copy of the database.", "Bacula retrieves the files from a backup job. The project imports them into a separate database and verifies the restored auction record."],
                    ["<b>Point-in-time recovery (PITR)</b>", "You need the database from just before a deletion or corruption.", "PostgreSQL loads a physical base backup and replays archived WAL up to the chosen time. The local drill recovered a decision created after the base backup."],
                    ["<b>Encrypted S3 backup</b>", "The local machine or backup disk is lost.", "Retrieve an exact saved version from remote storage. The project tested a real encrypted S3 restore and verified retention protection. Continuous production WAL recovery from an independently managed account remains unproven."],
                ],
                [0.23, 0.26, 0.51],
            ),
            p("Two terms you may be asked about", "heading"),
            p("<b>RPO</b> tells you how much recent data you could lose. For Bacula, it depends on the age of the snapshot you can restore. For PITR, it depends on how far the archived changes go."),
            p("<b>RTO</b> tells you how long it takes to restore service. A full timer includes retrieving the backup, checking the data, and getting the app back online."),
            *hint("Use this page to answer which tool you would use for a dead database server, a mistaken deletion, or a lost backup disk."),
        ],
        [
            *start("Bacula, step by step", "Bacula protects a prepared database copy. The restore check shows whether that copy can really recover the auction."),
            p("1. Prepare the files", "heading"),
            p("The backup script exports PostgreSQL from one consistent snapshot. It writes a manifest with the checkpoint time, record counts, and a checksum that can detect a changed dump."),
            p("2. Save the files", "heading"),
            p("The <b>Director</b> runs the job. The <b>File Daemon</b> reads the prepared files. The <b>Storage Daemon</b> writes the backup media. The <b>Catalog</b> tracks which job saved each file and where to retrieve it."),
            p("3. Restore to a safe place", "heading"),
            p("Bacula retrieves the chosen files into a separate folder. The recovery script checks their checksums, creates a new database, and imports the saved data there. The live database stays available for its own work."),
            p("4. Prove the result", "heading"),
            p("The script checks record counts and independently replays the audit history to recalculate the winners. The drill verified <b>20 decisions, 21 audit events, and 3 winners</b>. It recorded <b>PASS</b>."),
            p("What 1.25 seconds means", "heading"),
            p("The recorded <b>1.25 s</b> covers database import and verification in the rehearsal. Media retrieval, operator response, and rebuilding the site are outside that timer. The drill did not measure full-site RTO or RPO."),
            *hint("Show Bacula backup job <b>1</b> and restore job <b>2</b> with <b>T</b> status. Then show the restore certificate and point to the checks and winner count."),
            p("Project references: docs/recovery.md, docs/ha-deployment.md, docs/measurements.md, docs/evidence/recovery-bacula.json", "note"),
        ],
    ]


def decorate(canvas, doc):
    canvas.setStrokeColor(TEAL)
    canvas.setLineWidth(1)
    canvas.line(MARGIN, A4[1] - 36, A4[0] - MARGIN, A4[1] - 36)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(NAVY)
    canvas.drawString(MARGIN, A4[1] - 27, "AEGISBID OMEGA")
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(A4[0] - MARGIN, A4[1] - 27, "SYSTEM FLOW AND RECOVERY")
    canvas.setStrokeColor(LINE)
    canvas.line(MARGIN, 35, A4[0] - MARGIN, 35)
    canvas.drawString(MARGIN, 22, "Talha Adil  ·  CS-23114")
    canvas.drawRightString(A4[0] - MARGIN, 22, f"{doc.page} / 5")


def main():
    pages = page_content()
    story = []
    for index, page in enumerate(pages):
        if index:
            story.append(PageBreak())
        story.extend(page)
    SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=52,
        bottomMargin=50,
        title="AegisBid Omega | System flow and recovery",
        author="Talha Adil",
    ).build(story, onFirstPage=decorate, onLaterPages=decorate)
    pdf = PdfReader(OUTPUT)
    titles = [page[0].getPlainText() for page in pages]
    if len(pdf.pages) != len(titles) or any(
        title not in page.extract_text() for title, page in zip(titles, pdf.pages, strict=True)
    ):
        raise RuntimeError("Guide pages do not match the planned layout.")
    print(OUTPUT)


if __name__ == "__main__":
    main()

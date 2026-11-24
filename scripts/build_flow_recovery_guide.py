"""Build the one-page AegisBid presentation script."""

import itertools
import re
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/submission/AegisBid_Flow_and_Recovery_Guide.pdf"
MARGIN = 41
WIDTH = A4[0] - 2 * MARGIN - 12
INK = HexColor("#142B3D")
TEAL = HexColor("#076355")
MUTED = HexColor("#3F5868")
PALE = HexColor("#EAF4F1")
LINE = HexColor("#CBDAD9")

SCRIPT = [
    (
        0,
        16,
        "Seller studio",
        (
            "AegisBid is a flash auction app. Here, a seller lists one keyboard starting at $100. "
            "A bidder places an offer, and the seller can watch the latest bids."
        ),
    ),
    (
        16,
        42,
        "Bidder screen and bid history",
        (
            "Nginx routes the bid to Go, which groups requests when many arrive together. "
            "FastAPI checks the account, then PostgreSQL saves the bid and gives it a place in line. "
            "Queued means saved. The worker checks offers in order."
        ),
    ),
    (
        42,
        68,
        "Latest bids and Worker leadership",
        (
            "If two people offer $100, the first is accepted and the next minimum becomes $105. "
            "If the worker crashes, another can take over and check the saved bids. NATS passes messages between services. "
            "Retrying with the same request ID counts once. The worker finishes bids saved before the deadline, then picks the winner."
        ),
    ),
    (
        68,
        92,
        "PostgreSQL failover design",
        (
            "In production, one PostgreSQL primary sends its change log to two standbys. "
            "At least one standby must save the change before the primary confirms the write. "
            "If the primary fails, a safe standby takes over. We demonstrated this in the local lab."
        ),
    ),
    (
        92,
        120,
        "Bacula job list and restore certificate",
        (
            "Bacula saves a consistent database export. We restored it into a separate database, checked the files, "
            "and recalculated the winners. The drill verified 20 decisions and three winners. "
            "Archived changes let PostgreSQL recover to a chosen time, and encrypted S3 keeps a remote copy."
        ),
    ),
]

STYLES = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=29, leading=34, textColor=INK, spaceAfter=7),
    "meta": ParagraphStyle("meta", fontName="Helvetica-Bold", fontSize=11.5, leading=16, textColor=TEAL, spaceAfter=15),
    "prep": ParagraphStyle("prep", fontName="Helvetica", fontSize=11.5, leading=16, textColor=MUTED, spaceAfter=12),
    "time": ParagraphStyle("time", fontName="Helvetica-Bold", fontSize=12, leading=17, textColor=TEAL),
    "cue": ParagraphStyle("cue", fontName="Helvetica-Bold", fontSize=10.5, leading=15, textColor=TEAL, spaceAfter=4),
    "say": ParagraphStyle("say", fontName="Helvetica", fontSize=13, leading=18.5, textColor=INK),
}


def timestamp(seconds):
    return f"{seconds // 60}:{seconds % 60:02}"


def decorate(canvas, doc):
    canvas.setStrokeColor(TEAL)
    canvas.line(MARGIN, A4[1] - 35, A4[0] - MARGIN, A4[1] - 35)
    canvas.setFillColor(TEAL)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(MARGIN, A4[1] - 26, "AEGISBID OMEGA")
    canvas.drawRightString(A4[0] - MARGIN, A4[1] - 26, "DEMO SCRIPT")


def main():
    if (
        SCRIPT[0][0] != 0
        or SCRIPT[-1][1] != 120
        or any(left[1] != right[0] for left, right in itertools.pairwise(SCRIPT))
    ):
        raise RuntimeError("The five segments must cover exactly two minutes.")
    words = sum(len(re.findall(r"[\w$]+", spoken)) for _, _, _, spoken in SCRIPT)
    if not 190 <= words <= 235:
        raise RuntimeError(f"The narration should be easy to read in two minutes. Got {words} words.")

    rows = [
        [
            Paragraph(f"{timestamp(start)}<br/>– {timestamp(end)}", STYLES["time"]),
            [Paragraph(show, STYLES["cue"]), Paragraph(spoken, STYLES["say"])],
        ]
        for start, end, show, spoken in SCRIPT
    ]
    sequence = Table(rows, colWidths=[64, WIDTH - 64])
    sequence.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PALE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.6, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
                ("LEFTPADDING", (0, 0), (-1, -1), 11),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )

    story = [
        Paragraph("AegisBid in two minutes", STYLES["title"]),
        Paragraph("Talha Adil · CS-23114", STYLES["meta"]),
        Paragraph(
            "<b>Before you start</b> &nbsp; Open an auction, the Admin dashboard, and the Bacula restore certificate. "
            "Read the larger text aloud. The green text tells you what to show.",
            STYLES["prep"],
        ),
        sequence,
    ]
    SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=51,
        bottomMargin=31,
        title="AegisBid in two minutes",
        author="Talha Adil",
    ).build(story, onFirstPage=decorate)
    pdf = PdfReader(OUTPUT)
    if len(pdf.pages) != 1 or "2:00" not in pdf.pages[0].extract_text():
        raise RuntimeError("The complete script must fit on one page.")
    print(f"{OUTPUT} ({words} spoken words)")


if __name__ == "__main__":
    main()

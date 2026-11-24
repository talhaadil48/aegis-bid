"""Build five cue cards for the AegisBid three-minute video."""

import re
from itertools import pairwise
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/submission/AegisBid_3_Minute_Video_Script.pdf"
INK = HexColor("#142B3D")
TEAL = HexColor("#076355")
PALE = HexColor("#EAF4F1")
LINE = HexColor("#CBDAD9")
MARGIN = 48
WIDTH = A4[0] - 2 * MARGIN - 12

CARDS = [
    {
        "slot": (0, 35),
        "title": "Create the auction",
        "show": [
            "Start on the report's system flowchart. Point to Nginx, Go, and PostgreSQL.",
            "Switch to <b>Seller studio</b> and publish the prefilled keyboard auction.",
        ],
        "say": (
            "Hi, I’m Talha Adil, CS-23114. This is AegisBid, a flash auction app with verified database recovery. "
            "I’m listing one keyboard at $100, with a $5 minimum increase. Nginx routes the traffic. "
            "Go groups incoming bids and runs the separate live feed. PostgreSQL keeps the official auction record."
        ),
        "note": (
            "<b>Before recording</b><br/>"
            "Open separate browser profiles for the seller, two bidders, and the admin. In the seller form, "
            "prefill stock <b>1</b>, reserve <b>10000</b> cents, and increment <b>500</b> cents. "
            "Set the opening time to a minute ago and the deadline to ten minutes from now. "
            "Leave the form ready to submit. Open the report at pages 2 and 6, the Bacula job list, "
            "and the restore certificate. Keep passwords offscreen."
        ),
    },
    {
        "slot": (35, 75),
        "title": "Place and track the bids",
        "show": [
            "Refresh the bidder screen, select the new auction, and submit <b>10000</b> cents.",
            "Switch to the second bidder after the price updates and submit <b>10500</b> cents.",
            "Return to the seller screen and point to <b>Latest bids</b> and their decisions.",
        ],
        "say": (
            "I’ll start with a $100 offer. Queued means PostgreSQL has already saved the request. "
            "The worker checks bids in order. Once this offer is accepted, the next minimum becomes $105. "
            "A second bidder offers that amount. The seller can see both decisions. If the reply gets lost, "
            "retrying with the same request ID avoids a duplicate bid."
        ),
        "note": (
            "<b>If Queued disappears quickly</b><br/>"
            "Point to the accepted result in <b>Your bid history</b> or <b>Latest bids</b>. "
            "The worker may finish before the next screen refresh."
        ),
    },
    {
        "slot": (75, 106),
        "title": "Show failure handling and the winner",
        "show": [
            "Point to <b>Worker leadership</b> in the admin dashboard.",
            "Return to the seller. Select <b>End auction</b>, confirm, and show <b>Final allocation</b>.",
        ],
        "say": (
            "The admin can see which worker is in charge. If that worker stops, another can take over and continue "
            "from the saved bids. NATS passes messages, and the worker can also find waiting bids in PostgreSQL. "
            "When I close the auction, the system finishes the eligible bids first. The winning offer is $105."
        ),
        "note": (
            "<b>If allocation takes a moment</b><br/>"
            "Explain that <b>Closing</b> gives the worker time to finish the queue. "
            "When the result appears, point to the winning amount. The seller can also export the audit."
        ),
    },
    {
        "slot": (106, 150),
        "title": "Prove Bacula can restore the data",
        "show": [
            "Show the Bacula job list. Point to backup job <b>1</b>, restore job <b>2</b>, and <b>T</b> status.",
            "Switch to the restore certificate. Point to <b>PASS</b>, the checksum result, and the winner count.",
        ],
        "say": (
            "Here are the Bacula backup and restore jobs. T means each job finished normally. "
            "PostgreSQL exports a consistent copy. Bacula’s Director runs the job, its File Daemon reads the files, "
            "and its Storage Daemon saves them. The Catalog tracks where they are. "
            "We restored into a separate database, checked the files, and recalculated the winners. "
            "We verified 20 decisions, 21 audit events, and three winners. The 1.25 seconds covers import and verification."
        ),
        "note": (
            "<b>Files to open before recording</b><br/>"
            "Job list: <font face='Courier'>docs/evidence/bacula-console.txt</font><br/>"
            "Certificate: <font face='Courier'>docs/evidence/recovery-bacula.html</font><br/>"
            "Show these recorded results while you talk."
        ),
    },
    {
        "slot": (150, 180),
        "title": "Close with the test results",
        "show": [
            "Show the technical report's <b>page 6</b> with the two recorded 50,000-bid runs.",
            "Point to the worker-kill column. If you have time, show <b>ha-local.json</b> beside it.",
        ],
        "say": (
            "Two earlier HTTP tests each admitted bids from 50,000 different users in the final ten seconds, including one with a worker crash. "
            "Those are results for those test runs. In the production design, one PostgreSQL primary sends changes to two standbys "
            "and waits for one to confirm. We tested standby takeover in a local lab. The full AWS setup is still a design."
        ),
        "note": (
            "<b>Keep handy for questions</b><br/>"
            "Local failover took about <b>67 seconds</b> with verification. The separate live demo handled "
            "<b>1,500 requests from 500 test bidders</b>. PostgreSQL can also replay archived changes up to a chosen time. "
            "Encrypted S3 stores an offsite copy. Later layouts have yet to repeat the full 50,000-bid performance reliably."
        ),
    },
]

STYLES = {
    "time": ParagraphStyle("time", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=TEAL, spaceAfter=9),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=32, leading=37, textColor=INK, spaceAfter=22),
    "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=12, leading=17, textColor=TEAL, spaceAfter=7),
    "action": ParagraphStyle("action", fontName="Helvetica", fontSize=14, leading=20, textColor=INK, spaceAfter=8),
    "say": ParagraphStyle("say", fontName="Helvetica", fontSize=19, leading=27, textColor=INK),
    "note": ParagraphStyle("note", fontName="Helvetica", fontSize=12.5, leading=18, textColor=INK),
}


def stamp(seconds):
    return f"{seconds // 60}:{seconds % 60:02}"


def frame(canvas, doc):
    canvas.setStrokeColor(TEAL)
    canvas.line(MARGIN, A4[1] - 35, A4[0] - MARGIN, A4[1] - 35)
    canvas.setFillColor(INK)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(MARGIN, A4[1] - 25, "AEGISBID  /  THREE-MINUTE VIDEO")
    canvas.setStrokeColor(LINE)
    canvas.line(MARGIN, 36, A4[0] - MARGIN, 36)
    canvas.setFont("Helvetica", 10)
    canvas.drawString(MARGIN, 22, "Talha Adil  ·  CS-23114")
    canvas.drawRightString(A4[0] - MARGIN, 22, f"{doc.page} / {len(CARDS)}")


def main():
    slots = [card["slot"] for card in CARDS]
    if slots[0][0] != 0 or slots[-1][1] != 180 or any(a[1] != b[0] for a, b in pairwise(slots)):
        raise RuntimeError("Cue cards must cover three minutes in order.")
    story = []
    for index, card in enumerate(CARDS):
        if index:
            story.append(PageBreak())
        begin, end = card["slot"]
        story.extend(
            [
                Paragraph(f"{stamp(begin)}–{stamp(end)}", STYLES["time"]),
                Paragraph(card["title"], STYLES["title"]),
                Paragraph("SHOW", STYLES["label"]),
            ]
        )
        story.extend(
            Paragraph(f"<b>{step}.</b> {action}", STYLES["action"]) for step, action in enumerate(card["show"], start=1)
        )
        story.extend([Spacer(1, 13), Paragraph("SAY", STYLES["label"]), Paragraph(card["say"], STYLES["say"])])
        note = Table([[Paragraph(card["note"], STYLES["note"])]], colWidths=[WIDTH])
        note.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PALE),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
                    ("LEFTPADDING", (0, 0), (-1, -1), 14),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 13),
                    ("TOPPADDING", (0, 0), (-1, -1), 11),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
                ]
            )
        )
        story.extend([Spacer(1, 21), note])
    SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        topMargin=57,
        bottomMargin=48,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        title="AegisBid | Three-minute video script",
        author="Talha Adil",
    ).build(story, onFirstPage=frame, onLaterPages=frame)
    pdf = PdfReader(OUTPUT)
    if len(pdf.pages) != len(CARDS) or any(
        card["title"] not in " ".join(page.extract_text().split()) for card, page in zip(CARDS, pdf.pages, strict=True)
    ):
        raise RuntimeError("Each scene needs its own complete cue card.")
    words = sum(len(re.findall(r"[\w$]+", card["say"])) for card in CARDS)
    print(f"{OUTPUT} ({words} spoken words, {len(pdf.pages)} cards)")


if __name__ == "__main__":
    main()

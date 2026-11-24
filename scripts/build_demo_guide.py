"""Build the separate two-page, exactly 180-second presentation guide."""

import json
from html import escape

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.platypus import PageBreak, SimpleDocTemplate

from scripts.build_report import NAVY, ROOT, TEAL, blocks


def paragraph(text):
    return {"type": "p", "text": text}


def heading(text):
    return {"type": "h", "text": text}


def code(text):
    return {"type": "code", "text": text}


def main():
    identity = json.loads((ROOT / "docs/report/report-content.json").read_text(encoding="utf-8"))
    name, roll = identity["student_name"], identity["roll_number"]
    pages = [
        {
            "title": "Your three-minute demonstration",
            "blocks": [
                paragraph(
                    f"<b>Presenter:</b> {escape(name)} | {escape(roll)}.<br/>"
                    "<b>Recording:</b> use your own voice. The eight slots below total exactly 180 seconds. Pre-open the tabs and rehearse once. Historical evidence must be described as recorded evidence."
                ),
                {
                    "type": "table",
                    "headers": ["Time", "Show", "Say / explain"],
                    "widths": [0.14, 0.32, 0.54],
                    "rows": [
                        [
                            "0:00-0:12",
                            "Title/name + implementation stack on report page 1",
                            f"I am {name}, {roll}. AegisBid combines durable flash auctions with Bacula-backed, independently verified database recovery.",
                        ],
                        [
                            "0:12-0:32",
                            "Report page 2: complete system flow",
                            "Trace the bid into SQL and the fenced worker, then follow the recovery branch. Bacula protects prepared database artifacts; restored data is verified in a separate database.",
                        ],
                        [
                            "0:32-0:55",
                            "Live bidder screen; submit one bid",
                            "Reserve $100, increment $5, stock 3. Show pending then final state in private history. QUEUED means durable admission, not winning stock. Seller/admin views are already open.",
                        ],
                        [
                            "0:55-1:10",
                            "Terminal: --race; refresh private history",
                            "Two authenticated bidders offer the same eligible price. Show one ACCEPTED and one REJECTED, with different ordered sequences. Stable request UUIDs make retries idempotent.",
                        ],
                        [
                            "1:10-1:40",
                            "Report page 3 + terminal: --bacula",
                            "Explain Director, File Daemon, Storage Daemon and Catalog. Show recorded jobs 1/2 with T status, four entries and 39,802 bytes. Prepared SQL exports and checksum manifests are backed up; media and Catalog are persistent.",
                        ],
                        [
                            "1:40-2:10",
                            "Report page 4 + recovery-bacula.json",
                            "Show PASS, checksum_verified=true, 20 decisions, 21 events and three winners. Restore used an alternate path and fresh database. The recorded 1.25218 s covers database import/verification; media retrieval and full-site recovery are outside that timer.",
                        ],
                        [
                            "2:10-2:40",
                            "Report page 6 + --verify-bidding",
                            "Present two selected historical HTTP runs: each accounted for 50,000 distinct requests, with normal/worker-kill verification passing. Show queue/drain time and replay 50,000 signed decisions with 20 winners. These recorded successes do not certify every current layout.",
                        ],
                        [
                            "2:40-3:00",
                            "Terminal: --late (or rehearsed --closed-test)",
                            "Show terminal CLOSED for a new late UUID and unchanged sealed anchor/winners. If using the fallback, label it live isolated API/database checks and show 3 passed. Finish on correct allocation and the remaining production limits.",
                        ],
                    ],
                },
                heading("Delivery cues"),
                paragraph(
                    "Pre-open the browser, report pages 2/3/4/6 and terminals. Bacula is the main demonstration: show job T status and the separate restore certificate together. Expected outputs: --race one ACCEPTED/one REJECTED; offline replay PASS with 50,000 requests/20 winners; --late CLOSED with unchanged anchor/winners."
                ),
                paragraph(
                    "Pre-expand the evidence output or use a clearly labelled recorded clip when a step exceeds its slot. Do not call stored JSON a live stress experiment. The failure test sends real SIGKILL and explicitly restarts the worker. HTTP pools are bounded; 50,000 virtual bidders does not mean 50,000 simultaneous HTTP transactions."
                ),
            ],
        },
        {
            "title": "Preparation, commands and fallback",
            "blocks": [
                heading("1. Prepare locally before recording"),
                paragraph(
                    "Use PowerShell at the repository root with local .env and seeded accounts. Running containers can predate the fixes: follow docs/runbook.md to upgrade and rehearse first. --check verifies reachability, not code version. Keep credentials/cookies offscreen. Helpers make no AWS calls."
                ),
                code(
                    ".venv\\Scripts\\python.exe -m scripts.demo --check\n.venv\\Scripts\\python.exe -m scripts.demo --prepare"
                ),
                paragraph(
                    "Open <b>http://localhost:18080</b>; select the printed <b>CEP demo HH:MM UTC</b> auction: 45 minutes, stock 3, reserve 10000 cents, increment 500 cents. Use separate browser profiles for bidder1, seller, admin and auditor; tabs share cookies. Rehearse --race and --late and require PASS, then rerun --prepare for a fresh recording auction. --check confirms reachability/auth, not version readiness."
                ),
                heading("2. Pretype these in separate terminal tabs"),
                code(
                    ".venv\\Scripts\\python.exe -m scripts.demo --race\n.venv\\Scripts\\python.exe -m scripts.demo --bacula\nGet-Content docs/evidence/recovery-bacula.json\n.venv\\Scripts\\python.exe -m scripts.demo --verify-bidding\n.venv\\Scripts\\python.exe -m scripts.demo --late"
                ),
                paragraph(
                    "--race uses two bidders at the same eligible price. --bacula reads existing Catalog jobs; the certificate JSON is recorded recovery evidence. --verify-bidding replays saved client requests/signature/ledger offline. --late closes this auction: run it last. No command above starts a new backup, restore or full-load experiment."
                ),
                heading("3. Open the evidence files in advance"),
                paragraph(
                    "<b>Report:</b> pages 2 (flow), 3 (Bacula), 4 (restore) and 6 (selected 50k successes). <b>Recovery:</b> docs/evidence/recovery-bacula.json/.html and bacula-console.txt. <b>Workload:</b> docs/bidding-proof.md and docs/evidence/bidding-index.json retain complete run history. Avoid displaying credentials or private bucket details."
                ),
                paragraph(
                    "The live auditor is INCOMPLETE without AUDIT_SIGNING_KEY. --verify-bidding checks the saved signed export; its public key must be distributed/pinned separately for trusted provenance. Owner receipts are hash references, not separate signatures."
                ),
                heading("4. If something is unavailable"),
                paragraph(
                    "After --late or expiration, rerun --prepare. If --late fails, upgrade/rehearse or replace its slot with the isolated API test below: expect 3 passed. This helper loads the private .env, enables integration checks and creates a separate test database. PostgreSQL must be running and its configured user able to create that database. Never improvise a successful result or reset live data volumes."
                ),
                code(".venv\\Scripts\\python.exe -m scripts.demo --closed-test"),
                paragraph(
                    "If Bacula is stopped, show recorded completed jobs/recovery JSON. If a live command fails, use a pre-recorded successful rehearsal and label it recorded. Keep 50k runs, kind failures, cloud backups and restores outside this presentation. For an interrupted optional --recover, restart only the stopped worker container with docker start; Compose start can rerun migration dependencies."
                ),
                heading("Likely viva questions: concise answers"),
                paragraph(
                    "<b>Why Bacula?</b> Scheduled artifact protection, media/Catalog indexing and alternate-path restore. <b>T means correct data?</b> It means normal job completion; checksum/count/rule/winner checks establish recovered-data correctness. <b>1.25 s full-site RTO?</b> It times only import/verification. <b>100%?</b> Full request coverage in the two selected historical runs, not every release or production scenario. <b>Production scope?</b> Current-layout repeatability, real multi-zone, independent-account backup and continuous offsite RPO remain open."
                ),
            ],
        },
    ]
    cursor = 0
    for row in pages[0]["blocks"][1]["rows"]:
        begin, end = [
            sum(int(value) * factor for value, factor in zip(stamp.split(":"), (60, 1), strict=True))
            for stamp in row[0].split("-")
        ]
        if begin != cursor or end <= begin:
            raise RuntimeError("Demo slots must be consecutive and positive")
        cursor = end
    if cursor != 180:
        raise RuntimeError("Demo timeline must total exactly 180 seconds")
    output = ROOT / "docs/submission/AegisBid_3_Minute_Demo_Guide.pdf"
    story = []
    for index, page in enumerate(pages):
        if index:
            story.append(PageBreak())
        story.extend(blocks(page, 10, A4[0] - 84))

    def decorate(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(42, A4[1] - 20, "AEGISBID OMEGA  |  PRESENTATION GUIDE")
        canvas.setStrokeColor(TEAL)
        canvas.line(42, A4[1] - 28, A4[0] - 42, A4[1] - 28)
        canvas.drawRightString(A4[0] - 42, 22, str(doc.page))

    SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=42,
        bottomMargin=38,
        title="AegisBid Omega | Three-minute demo guide",
        author=name,
    ).build(story, onFirstPage=decorate, onLaterPages=decorate)
    reader = PdfReader(output)
    if len(reader.pages) != 2 or pages[1]["title"] not in reader.pages[1].extract_text():
        raise RuntimeError("Demo guide must contain two correctly arranged pages")
    html = "<!doctype html><meta charset='utf-8'><title>AegisBid demo guide</title><style>body{max-width:980px;margin:40px auto;font:17px/1.5 system-ui;color:#16334d}table{border-collapse:collapse}td,th{border:1px solid #ccd;padding:10px;vertical-align:top}pre{background:#eef3f5;padding:12px;white-space:pre-wrap}h1,h2{color:#126c78}</style>"
    for page in pages:
        html += "<h1>" + escape(page["title"]) + "</h1>"
        for block in page["blocks"]:
            if block["type"] == "table":
                html += "<table><tr>" + "".join("<th>" + escape(v) + "</th>" for v in block["headers"]) + "</tr>"
                html += (
                    "".join(
                        "<tr>" + "".join("<td>" + escape(v) + "</td>" for v in row) + "</tr>" for row in block["rows"]
                    )
                    + "</table>"
                )
            elif block["type"] == "code":
                html += "<pre>" + escape(block["text"]) + "</pre>"
            else:
                tag = "h2" if block["type"] == "h" else "p"
                html += f"<{tag}>{block['text']}</{tag}>"
    output.with_suffix(".html").write_text(html, encoding="utf-8")
    print("PASS: 180-second timeline; two-page PDF and searchable HTML guide")


if __name__ == "__main__":
    main()

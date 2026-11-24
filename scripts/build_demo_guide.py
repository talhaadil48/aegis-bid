"""Build the separate two-page, exactly 180-second presentation guide."""

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
    pages = [
        {
            "title": "Your three-minute demonstration",
            "blocks": [
                paragraph(
                    "<b>Recording:</b> show your project title, name and roll number first; use your own voice. The eight slots below total exactly 180 seconds. Pre-open the tabs and rehearse once. Historical evidence must be described as recorded evidence."
                ),
                {
                    "type": "table",
                    "headers": ["Time", "Show", "Say / explain"],
                    "widths": [0.14, 0.32, 0.54],
                    "rows": [
                        [
                            "0:00-0:12",
                            "Title + architecture on report page 1",
                            "AegisBid Omega: durable flash auctions with independent verification and disaster recovery. Name, roll number, project objective.",
                        ],
                        [
                            "0:12-0:32",
                            "Report page 2: complete system flow",
                            "Trace HTTP bid to Go intake, FastAPI authentication, durable SQL queue, fenced worker, atomic decisions and final allocation. Separate live fanout and verified recovery branches.",
                        ],
                        [
                            "0:32-0:55",
                            "Live bidder screen; submit one bid",
                            "Reserve $100, increment $5, stock 3. Show pending then final state in private history. QUEUED means durable admission, not winning stock. Seller/admin views are already open.",
                        ],
                        [
                            "0:55-1:15",
                            "Terminal: --race; refresh private history",
                            "Two authenticated bidders offer the same eligible price. Show one ACCEPTED and one REJECTED, with different ordered sequences. Stable request UUIDs make retries idempotent.",
                        ],
                        [
                            "1:15-1:55",
                            "Terminal: --bidding; report page 7",
                            "Label these recorded tests. 50,000 distinct authenticated users offered bids in the final ten seconds; normal and actual worker-SIGKILL HTTP runs passed. Show zero errors/missing/late, accepted/rejected/queued counts, drain time and 20 verified winners. State the live-profile result exactly as recorded.",
                        ],
                        [
                            "1:55-2:15",
                            "Terminal: --verify-bidding",
                            "Replay the saved original client requests against signed events: 50,000 bidder/UUID/amount matches, rule replay and 20 winners. Tampered winners fail. This verification runs now; the stress workload itself was recorded earlier.",
                        ],
                        [
                            "2:15-2:40",
                            "Recorded recovery evidence; --evidence",
                            "Bacula restored 20 decisions and three winners. Kind node-loss recovery took 67.21 seconds; PITR 3.12 seconds; encrypted S3 restore passed. These are controlled recorded drills. Physical multi-zone AWS deployment and independent-account backup remain pending.",
                        ],
                        [
                            "2:40-3:00",
                            "Terminal: --late; final winners",
                            "Close the demo auction, submit a new UUID and show terminal CLOSED. The owner sees the same state; the sealed anchor and winners remain unchanged. Finish on correct allocation and transparent production limits.",
                        ],
                    ],
                },
                heading("Delivery cues"),
                paragraph(
                    "Keep browser, terminal and PDF viewer arranged before starting. Point to one useful field at a time. Spend the most attention on the distinct-bidder and crash results. Admission within ten seconds does not mean all decisions finish by cutoff: show the recorded backlog and tail. Do not read every row."
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
                    "Run these from the repository root in PowerShell, with the existing local .env and seeded users. DEMO_PASSWORD must match those accounts. Never display .env, cookie caches, passwords or AWS credentials in the video. These helpers do not invoke AWS."
                ),
                code(
                    ".venv\\Scripts\\python.exe -m scripts.demo --check\n.venv\\Scripts\\python.exe -m scripts.demo --prepare"
                ),
                paragraph(
                    "Open <b>http://localhost:18080</b>. Select the new <b>CEP demo HH:MM UTC</b> title printed by --prepare. It lasts 45 minutes, has stock 3, reserve 10000 cents and increment 500 cents. Use distinct browser profiles or different browsers for bidder1, seller, admin and auditor; ordinary tabs share login cookies. Sign in before recording. Prepare a fresh auction after rehearsal."
                ),
                heading("2. Pretype these in separate terminal tabs"),
                code(
                    ".venv\\Scripts\\python.exe -m scripts.demo --race\n.venv\\Scripts\\python.exe -m scripts.demo --bidding\n.venv\\Scripts\\python.exe -m scripts.demo --verify-bidding\n.venv\\Scripts\\python.exe -m scripts.demo --evidence\n.venv\\Scripts\\python.exe -m scripts.demo --late"
                ),
                paragraph(
                    "--race uses bidder1 and bidder2 at the current eligible amount; avoid concurrent manual bids. --bidding reads selected immutable runs from docs/evidence/bidding-index.json. --verify-bidding independently replays the saved full client CSV and signed ledger. --late closes this demo auction, checks a new terminal request and unchanged anchor/winners: run it last. Optional --recover kills/restarts the local worker and tests 20 same-UUID retries; rehearse that separately. --bacula lists existing Catalog jobs."
                ),
                heading("3. Open the evidence files in advance"),
                paragraph(
                    "<b>Report:</b> AegisBid_Technical_Report_7_Pages.pdf, especially pages 2 and 7. <b>Bidding:</b> docs/bidding-proof.md and docs/evidence/bidding-index.json, with the selected run summaries. <b>Recovery:</b> recovery-bacula.json, bacula-console.txt, ha-local.json, pitr-local.json and s3-offsite.json. These are inside docs/evidence. The helper selects safe fields; avoid displaying private bucket/account details."
                ),
                paragraph(
                    "The live auditor screen correctly shows INCOMPLETE without AUDIT_SIGNING_KEY. Do not label it trusted PASS. The saved stress export is signed; --verify-bidding checks the included public key. For independent provenance, distribute/pin that key separately: downloading an export and adjacent key alone does not establish institutional trust. An owner receipt hash is not an independently signed receipt."
                ),
                heading("4. If something is unavailable"),
                paragraph(
                    "After --late or an expired auction, rerun --prepare and select its new title. If optional --recover is interrupted, start the worker using the command below. Use README startup if the app is stopped. The ordered-intake upgrade requires coordinated migration; see docs/runbook.md. Never reset data volumes for this demo."
                ),
                code("docker compose --env-file .env -f infra/compose.yaml start worker"),
                paragraph(
                    "If Bacula is stopped, show the existing completed job listing and recovery report and label them recorded. Do not run a restore into the live demo database. Do not rerun the 50k test, kind failure drill or cloud backup inside the three-minute recording. Admin API socket metrics cover their own process; Go gateway socket metrics are at http://127.0.0.1:18081/metrics."
                ),
                heading("Likely viva questions: concise answers"),
                paragraph(
                    "<b>Exactly once?</b> One committed SQL effect per stable UUID; transport can redeliver. <b>50k proof?</b> Real distinct users and original HTTP requests, final-ten-second admission timestamps, reported queue/drain, full signed replay; state live-profile scope separately. <b>Why separate Go services?</b> Isolate HTTP intake from socket fanout. <b>HA vs backup?</b> Promotion handles a primary failure; WAL/PITR and remote copies address historical corruption/site loss. <b>Production complete?</b> Physical multi-zone, multi-host load, independent-account backups and continuous production offsite PITR/RPO remain. The closed-auction admission bug is fixed."
                ),
            ],
        },
    ]
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

    SimpleDocTemplate(str(output), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=38).build(
        story, onFirstPage=decorate, onLaterPages=decorate
    )
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

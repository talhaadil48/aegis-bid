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
                            "Title/name + implementation stack on report page 1",
                            "AegisBid Omega. PostgreSQL decides bids, Go handles ingress/fanout, NATS journals commands and Bacula/WAL/S3 protect recovery. State your name and roll number.",
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
                            "Say: two historical HTTP runs passed 50,000 distinct bidders, including real worker SIGKILL; all 20 winners replayed correctly. Point to cutoff queue and decision tail. Then show current regressions: HTTP 42,794 eligible; combined live 30,782. Current repeatable 50k is still open.",
                        ],
                        [
                            "1:55-2:15",
                            "Terminal: --verify-bidding",
                            "Run offline replay now: 50,000 original bidder/UUID/amount matches and 20 winners must PASS. The recorded stress checks also rejected tampered winners. The workload was recorded earlier; verification runs now.",
                        ],
                        [
                            "2:15-2:40",
                            "Recorded recovery evidence; --evidence",
                            "Bacula restored 20 decisions and three winners. Kind node-loss recovery took 67.21 seconds; PITR 3.12 seconds; encrypted S3 restore passed. These are controlled recorded drills. Physical multi-zone AWS deployment and independent-account backup remain pending.",
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
                    "Open the bidder browser, report pages 2/7 and prepared terminals before recording. For --race expect PASS with one ACCEPTED and one REJECTED. For --verify-bidding expect PASS, 50,000 matched requests and 20 winners. For --late expect CLOSED and unchanged anchor/winners. Admission within ten seconds does not mean every decision finishes by cutoff."
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
                    "Run from the repository root in PowerShell with local .env and seeded accounts; DEMO_PASSWORD must match. Running containers can predate the new code. Follow the coordinated image/migration upgrade in docs/runbook.md before relying on new fixes; this document update does not deploy the app. Keep secrets/cookie caches out of the recording. Helpers make no AWS calls."
                ),
                code(
                    ".venv\\Scripts\\python.exe -m scripts.demo --check\n.venv\\Scripts\\python.exe -m scripts.demo --prepare"
                ),
                paragraph(
                    "Open <b>http://localhost:18080</b>; select the printed <b>CEP demo HH:MM UTC</b> auction: 45 minutes, stock 3, reserve 10000 cents, increment 500 cents. Use separate browser profiles for bidder1, seller, admin and auditor; tabs share cookies. Rehearse --race and --late and require PASS, then rerun --prepare for a fresh recording auction. --check confirms reachability/auth, not version readiness."
                ),
                heading("2. Pretype these in separate terminal tabs"),
                code(
                    ".venv\\Scripts\\python.exe -m scripts.demo --race\n.venv\\Scripts\\python.exe -m scripts.demo --bidding\n.venv\\Scripts\\python.exe -m scripts.demo --verify-bidding\n.venv\\Scripts\\python.exe -m scripts.demo --evidence\n.venv\\Scripts\\python.exe -m scripts.demo --late"
                ),
                paragraph(
                    "--race uses bidder1/bidder2 at the same eligible amount; avoid concurrent manual bids. --bidding reads historical passes and latest trials; it does not generate load. --verify-bidding replays the saved CSV/signature/ledger offline. --late closes this auction and verifies a new CLOSED receipt: run it last. Optional --recover tests real SIGKILL plus 20 same-UUID retries outside the short video. --bacula lists existing jobs."
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
                    "After --late or expiration, rerun --prepare. If --late fails, upgrade/rehearse or replace its slot with the isolated API test below: expect 3 passed. This helper loads the private .env, enables integration checks and creates a separate test database. PostgreSQL must be running and its configured user able to create that database. Never improvise a successful result or reset live data volumes."
                ),
                code(".venv\\Scripts\\python.exe -m scripts.demo --closed-test"),
                paragraph(
                    "If Bacula is stopped, show recorded completed jobs/recovery JSON. If a live command fails, use a pre-recorded successful rehearsal and label it recorded. Keep 50k runs, kind failures, cloud backups and restores outside this presentation. For an interrupted optional --recover, restart only the stopped worker container with docker start; Compose start can rerun migration dependencies."
                ),
                heading("Likely viva questions: concise answers"),
                paragraph(
                    "<b>Exactly once?</b> One SQL effect per UUID; transport can redeliver. <b>50k proof?</b> Two historical distinct-user HTTP passes with backlog/drain and signed replay; later regressions and combined-live capacity remain open. <b>Why Go services?</b> Bounded ingress and shared-frame fanout; service separation is an attempted optimization. <b>HA vs backup?</b> Promotion handles primary loss; PITR/remote copies address corruption/site loss. <b>Production complete?</b> Real multi-zone, independent-account backup and continuous offsite RPO remain unproven."
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

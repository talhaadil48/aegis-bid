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
                            "0:12-0:42",
                            "Bidder screen; place one bid; seller view already open",
                            "Reserve $100, increment $5, stock 3. Submit and point to QUEUED then ACCEPTED in bid history. Seller sees auction activity; highest offer alone is not final allocation.",
                        ],
                        [
                            "0:42-1:05",
                            "Terminal: --race; admin view",
                            "Two authenticated bidders send the same eligible price concurrently. One commits first; the other is rejected under the global increment rule. Show the two decision sequences.",
                        ],
                        [
                            "1:05-1:30",
                            "Terminal: --recover; refresh bid history",
                            "This kills the worker with SIGKILL, retries the same UUID 20 times, restarts the worker and checks one accepted request. QUEUED means SQL admission, not final acceptance.",
                        ],
                        [
                            "1:30-1:55",
                            "Terminal: --bacula; recovery-bacula.json",
                            "Bacula jobs 1 and 2 completed with T status. The recorded isolated restore verifies 20 decisions, 21 events and three winners. This is real backup and restore evidence.",
                        ],
                        [
                            "1:55-2:15",
                            "Terminal: --evidence, first block",
                            "50,000 sockets were concurrently retained for 58.01 seconds: five generators, shared host and identity. This proves socket capacity; distinct bidders and bid throughput need separate measurements.",
                        ],
                        [
                            "2:15-2:40",
                            "Same terminal: HA, PITR and S3 blocks",
                            "Recorded kind node-loss recovery: 67.21 seconds; physical PITR: 3.12 seconds. An encrypted real S3 restore passed. Multi-zone AWS deployment remains unexecuted; the remote bucket uses the same account.",
                        ],
                        [
                            "2:40-3:00",
                            "Auditor view + report page 5",
                            "Auditors replay rules and check hash links. Ed25519 verification needs a trusted signing key; unsigned evidence is INCOMPLETE. Close: durability, one business effect per UUID, verifiable recovery; remaining production work is listed on page 7.",
                        ],
                    ],
                },
                heading("Delivery cues"),
                paragraph(
                    "Keep the browser, terminal and PDF viewer arranged before starting. Explain each result while the command runs. Point to one useful field at a time. Spend the most attention on the visible bid and crash recovery: they demonstrate behavior rather than configuration. Do not read every row of the report."
                ),
                paragraph(
                    "If the terminal evidence needs scrolling, expand it before recording. Use a short, clearly labelled recorded clip for any step that exceeds its slot. Do not silently skip time or call stored JSON a live experiment. The --recover restart is explicit; do not claim automatic restart from this demonstration."
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
                    ".venv\\Scripts\\python.exe -m scripts.demo --race\n.venv\\Scripts\\python.exe -m scripts.demo --recover\n.venv\\Scripts\\python.exe -m scripts.demo --bacula\n.venv\\Scripts\\python.exe -m scripts.demo --evidence"
                ),
                paragraph(
                    "--race uses bidder1 and bidder2 at the current eligible amount. Avoid manual bids during the race. --recover really stops the local Compose worker, retries one UUID 20 times and restarts it in a finally block. Successful output is ACCEPTED, matching_requests=1 and PASS. It writes only .cache/demo-recovery.json; historical measurements stay unchanged. --bacula lists existing Catalog jobs; --evidence only reads recorded reports."
                ),
                heading("3. Open the evidence files in advance"),
                paragraph(
                    "<b>Report:</b> AegisBid_Technical_Report_7_Pages.pdf, especially pages 1, 2, 5 and 7. <b>Backup:</b> docs/evidence/recovery-bacula.json and bacula-console.txt. <b>Recorded capacity/recovery:</b> sockets-8be4e979f1bb4723bfcb86fe7a90f37a/summary.json, ha-local.json, pitr-local.json and s3-offsite.json. The helper selects safe fields; avoid displaying raw bucket/account details."
                ),
                paragraph(
                    "The auditor screen may correctly show INCOMPLETE without AUDIT_SIGNING_KEY. Do not present it as a trusted signed PASS. To demonstrate signed verification, use an honestly labelled prior recording of the signed/tampered fixture check: RUN_INTEGRATION=1, then pytest tests/test_evidence.py -v in the configured local test environment. An owner receipt hash is not an independently signed receipt."
                ),
                heading("4. If something is unavailable"),
                paragraph(
                    "If the auction has expired, rerun --prepare and select its new title. If --recover is interrupted, ensure the worker is started with the command below. If the app is not running, use the normal Compose startup from README before recording. Never reset volumes for this demo."
                ),
                code("docker compose --env-file .env -f infra/compose.yaml start worker"),
                paragraph(
                    "If Bacula is stopped, show the existing completed job listing and recovery report and label them recorded. Do not run a restore into the live demo database. Do not rerun the 50k test, kind failure drill or cloud backup inside the three-minute recording. Admin API socket metrics cover their own process; Go gateway socket metrics are at http://127.0.0.1:18081/metrics."
                ),
                heading("Likely viva questions: concise answers"),
                paragraph(
                    "<b>Exactly once?</b> Stable UUID admission and one committed SQL effect; transport can redeliver. <b>Why NATS?</b> Durable command journal and retries; SQL intake and reconciliation close the publication gap. <b>Why a Go gateway?</b> Shared prepared frames and bounded coalescing reduce per-subscriber work. <b>HA vs backup?</b> HA handles a primary/node failure; WAL recovery restores a selected historical point, and remote copies address local loss. <b>Production complete?</b> No: real multi-zone exercise, independent-account backups, continuous production PITR/RPO proof, distinct-client capacity and the closed-auction admission guard remain."
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

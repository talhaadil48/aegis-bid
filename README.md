# AegisBid Omega

Transactional flash auctions with a durable PostgreSQL ledger, JetStream command journal, four role views, replay verification and isolated recovery tooling. See [implementation status](docs/implementation-status.md) for measured capabilities and deployment limits. The root build guide and architecture document describe the broader target.

## Local quick start

Requires Python 3.12+, Node 20+, Docker Engine/Compose, and Git. Run from this repository root.

1. Copy `.env.example` to `.env`; replace every placeholder. Use a URL-safe PostgreSQL password and a random session secret of at least 32 characters. Keep `.env` untracked.
2. `docker compose --env-file .env -f infra/compose.yaml up -d --build`
3. Seed accounts: `docker compose --env-file .env -f infra/compose.yaml run --rm -e DEMO_PASSWORD=<your-demo-password> api python -m scripts.seed_demo`. For a private shell, export the password and use `-e DEMO_PASSWORD` instead of putting it in command history.
4. Open `http://localhost:18080` (override with `WEB_PORT`). Accounts: `bidder1`, `bidder2`, `seller`, `admin`, `auditor`. Seeding does not reset existing passwords.

Ports bind to loopback. This is a disposable local deployment; do not expose it publicly without TLS, production secret management, external rate limits and independent backup infrastructure.

## Development and checks

```sh
python -m venv .venv
# Activate .venv for your shell, then:
pip install -r requirements.lock
pip install --no-deps -e .
python -m aegis.db
python -m scripts.seed_demo
uvicorn aegis.api:app --host 127.0.0.1 --port 58000
# Separate terminals, same database/NATS environment:
python -m aegis.pipeline worker
python -m aegis.pipeline relay
```

Export `DATABASE_URL`, `SESSION_SECRET`, `DEMO_PASSWORD`, and `NATS_URL` into each shell; Python does not implicitly load `.env`. Compose reads them through `--env-file`. On Windows use `127.0.0.1` for local database/NATS URLs.

The Next.js frontend builds with `cd apps/web && npm ci && npm run build`. Compose serves that export through Nginx, including same-origin API and WebSocket proxying. For frontend-only development `npm run dev` serves UI assets; use the Compose proxy for functional integration.

Run `ruff check aegis tests scripts` and `pytest -q`. To exercise infrastructure, set `RUN_INTEGRATION=1` and `RUN_NATS=1` against **disposable** PostgreSQL/JetStream instances. Tests add uniquely named fixtures; never point them at production. API contract: `http://localhost:58000/docs`.

## Decision rules

Currency uses integer cents. Each valid bid exceeds the current high by the configured increment. Retrying a request UUID with the same payload has one business effect; changing its payload returns 409. Admission uses a database timestamp and per-auction sequence. Queued bids admitted before close are drained before winner allocation. Top unique bidders win at most the auction stock and pay their own recorded offers. Payment collection is outside this prototype.

Admin metrics come from real database records. WebSockets send coalesced authoritative snapshots (one-second default, two seconds in current scale profiles) and reconnect automatically. Bid history resolves final status independently. API instances report their own socket count; horizontal aggregation requires Prometheus. [Recorded bidding proofs](docs/bidding-proof.md) include two historical 50,000-distinct-user final-window HTTP passes, normally and with a worker SIGKILL. Later layouts regressed; repeatable current-branch and combined-live capacity remain unproven. The historical HTTP runs used 5,120 pooled connections and drained final decisions after the deadline. Production multi-host capacity and full-site RPO/RTO remain unproven.

## Recovery and evidence

Production extensions are described in [the deployment and proof runbook](docs/production.md). The optional Go realtime gateway shares authoritative snapshots across large subscriber sets; the sharded generator measures overlapping held sockets separately from bid throughput.

The [HA commissioning guide](docs/ha-deployment.md) covers three-zone infrastructure, synchronous failover, TLS and continuous remote WAL recovery. Measured local proofs include 50,000 concurrently held sockets, physical PITR and a real Kubernetes worker-node outage. Offsite tools support authenticated encryption, exact-version restore and verified COMPLIANCE retention; backup credentials remain outside application containers.

See [recovery procedures](docs/recovery.md), [operations](docs/runbook.md), and [measured results](docs/measurements.md). `python -m scripts.rehearse_recovery` builds an isolated source and restore database for a non-destructive drill. PostgreSQL 18 client tools (`pg_dump`, `pg_restore`) must be on PATH. `python -m scripts.backup_export backup-staging/<new-run>` exports the configured database. Backup artifacts contain private records and stay untracked.

The Bacula profile has its own PostgreSQL Catalog, file daemon, storage daemon, persistent media and alternate restore directory. It is a local classroom deployment, not offsite protection. Set `BACULA_PASSWORD` to 24+ URL-safe random characters, then start with `docker compose --env-file .env -f infra/compose.bacula.yaml up -d --build`. Do not use `--remove-orphans` when running separate Compose files in the same project.

## Submission and demonstration

The [seven-page technical report](docs/submission/AegisBid_Technical_Report_7_Pages.pdf) contains six technical pages plus a complete system flowchart on page 2. It covers the stack, issue-by-issue changes, ordering/terminal outcomes, API roles, security/audit, recovery and measured results. Historical passes and current regressions are both explicit. The diagram is also available as [vector SVG](docs/submission/AegisBid_Complete_System_Flow.svg) and [PNG](docs/submission/AegisBid_Complete_System_Flow.png). An [editable Word companion](docs/submission/AegisBid_Technical_Report_Editable.docx) is included; PDF pagination is the validated submission format. Fill in your name and roll number before submitting.

Follow the [three-minute demo guide](docs/submission/AegisBid_3_Minute_Demo_Guide.pdf), also available as [searchable HTML](docs/submission/AegisBid_3_Minute_Demo_Guide.html). It gives exact timing, screens/commands, expected outputs and fallbacks. Use `python -m scripts.demo --check`, `--prepare` and `--race` for the app; `--bidding` displays historical passes and latest failed trials, while `--verify-bidding` replays saved client requests against signed evidence. `--late` closes the prepared demo auction and checks a terminal receipt; `--closed-test` runs three isolated API/database regression checks as an alternative. Rehearse against updated images first: `--check` alone does not verify the running code version. Optional `--recover` kills/restarts the worker; `--bacula` and `--evidence` show recorded operations. Helpers do not contact AWS or overwrite historical evidence.

Regenerate with `pip install -r requirements-report.lock`, `python -m scripts.build_report` and `python -m scripts.build_demo_guide`. The report source is `docs/report/report-content.json`; the builder verifies exactly seven PDF pages and the section assigned to each page. The submission workflow also builds both documents and uploads them as CI artifacts.

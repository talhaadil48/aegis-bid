# AegisBid Omega

Transactional flash auctions with a durable PostgreSQL ledger, JetStream command journal, four role views, replay verification and isolated recovery tooling. See [implementation status](docs/implementation-status.md) for measured capabilities and deployment limits. The root build guide and architecture document describe the broader target.

## Local quick start

Requires Python 3.12+, Node 20+, Docker Engine/Compose, and Git. Run from this repository root.

1. Copy `.env.example` to `.env`; replace every placeholder. Use a URL-safe PostgreSQL password and a random session secret of at least 32 characters. Keep `.env` untracked.
2. `docker compose --env-file .env -f infra/compose.yaml up -d --build`
3. Open `http://localhost:18080` (override with `WEB_PORT`) and select **Create an account**. Choose a username and a password of at least 12 characters. The app signs you in as a bidder.
4. To open the first auction on an empty installation, an operator can provision a seller with `docker compose --env-file .env -f infra/compose.yaml exec api python -m scripts.create_user my-seller --role seller`. Enter the password at the prompt, then sign in as that seller and use **Create an auction**. Use the same command with the appropriate role to provision administrators or auditors.

For an optional classroom demo, export `DEMO_PASSWORD` in your shell and run `docker compose --env-file .env -f infra/compose.yaml run --rm -e DEMO_PASSWORD api python -m scripts.seed_demo`. This seeds `bidder1`, `bidder2`, `seller`, `admin` and `auditor` without resetting existing passwords.

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

Admin metrics come from real database records. WebSockets send coalesced authoritative snapshots each second and reconnect automatically. Bid history resolves final status independently. API instances report their own socket count; horizontal aggregation requires Prometheus. A recorded 50,000-socket hold demonstrates shared-host connection capacity; distinct-client bid throughput and production RPO/RTO remain unproven.

## Recovery and evidence

Production extensions are described in [the deployment and proof runbook](docs/production.md). The optional Go realtime gateway shares authoritative snapshots across large subscriber sets; the sharded generator measures overlapping held sockets separately from bid throughput.

The [HA commissioning guide](docs/ha-deployment.md) covers three-zone infrastructure, synchronous failover, TLS and continuous remote WAL recovery. Measured local proofs include 50,000 concurrently held sockets, physical PITR and a real Kubernetes worker-node outage. Offsite tools support authenticated encryption, exact-version restore and verified COMPLIANCE retention; backup credentials remain outside application containers.

See [recovery procedures](docs/recovery.md), [operations](docs/runbook.md), and [measured results](docs/measurements.md). `python -m scripts.rehearse_recovery` builds an isolated source and restore database for a non-destructive drill. PostgreSQL 18 client tools (`pg_dump`, `pg_restore`) must be on PATH. `python -m scripts.backup_export backup-staging/<new-run>` exports the configured database. Backup artifacts contain private records and stay untracked.

The Bacula profile has its own PostgreSQL Catalog, file daemon, storage daemon, persistent media and alternate restore directory. It is a local classroom deployment, not offsite protection. Set `BACULA_PASSWORD` to 24+ URL-safe random characters, then start with `docker compose --env-file .env -f infra/compose.bacula.yaml up -d --build`. Do not use `--remove-orphans` when running separate Compose files in the same project.

## Submission and demonstration

The [seven-page technical report](docs/submission/AegisBid_Technical_Report_7_Pages.pdf) contains the original six technical pages plus a complete system flowchart on page 2. It describes transaction rules, realtime scaling, security, audit, HA, recovery and measured limits. The diagram is also available as [vector SVG](docs/submission/AegisBid_Complete_System_Flow.svg) and [PNG](docs/submission/AegisBid_Complete_System_Flow.png). An [editable Word companion](docs/submission/AegisBid_Technical_Report_Editable.docx) is included; PDF pagination is the validated submission format. Fill in your name and roll number before submitting.

Follow the [three-minute demo guide](docs/submission/AegisBid_3_Minute_Demo_Guide.pdf), also available as [searchable HTML](docs/submission/AegisBid_3_Minute_Demo_Guide.html). The local helper provides `python -m scripts.demo --check`, `--prepare`, `--race`, `--recover`, `--bacula` and `--evidence`. `--recover` kills and explicitly restarts the disposable local worker. The helper does not contact AWS or overwrite historical evidence.

Regenerate with `pip install -r requirements-report.lock`, `python -m scripts.build_report` and `python -m scripts.build_demo_guide`. The report source is `docs/report/report-content.json`; the builder verifies exactly seven PDF pages and the section assigned to each page. The submission workflow also builds both documents and uploads them as CI artifacts.

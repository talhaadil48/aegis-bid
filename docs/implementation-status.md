# Implementation and validation ledger

The two root documents are the requirements baseline. Proposed capacity and recovery objectives remain unproven until measured.

| Phase | Scope | Completion gate |
| --- | --- | --- |
| 01 | PostgreSQL schema, ordered engine, fencing, idempotency, allocation | Real PostgreSQL race/retry/cutoff tests; push branch; merge |
| 02 | Authentication, durable pipeline, API, live updates, role dashboards | API authorization and end-to-end tests; frontend build; push branch; merge |
| 03 | Independent verifier, signed evidence, monitoring, chaos, load tooling | Tamper and replay tests; measured workload; push branch; merge |
| 04 | Backup export, isolated restore, Bacula integration, runbooks | Export/restore rehearsal; record actual limits; push branch; merge |

Phases 01–03 are implemented, tested, pushed and merged. Phase 04 includes real Bacula backup and restore evidence plus verified isolated database imports; consult Git history for its final merge. See `measurements.md` for actual results.

Implemented stack: FastAPI for API, coalesced WebSocket gateway, Python worker and outbox relay; PostgreSQL authority; JetStream command journal; Next.js shared role-based frontend; Prometheus/Grafana; Bacula local rehearsal. Redis is intentionally omitted because no cache is needed for this slice. Go gateways and workers remain the documented advanced target. The baseline race harness uses controlled in-memory synchronization, not an unavailable V1 source repository.

Deferred beyond the tested local implementation: independent backup hosts/offsite immutability, continuous WAL/PITR, PostgreSQL standby promotion, multi-zone routing, adaptive fleet pre-warming, production key custody, payment settlement, full legacy-system comparison, and multi-host 50,000-client proof. Submission identity, narrated video and screenshots require the student's own material.

P2 remains a deployment extension: multi-zone load balancers, safely fenced database promotion, independent offsite storage, multi-host 50,000-client benchmarks, and predictive autoscaling. One workstation cannot demonstrate independent failure domains.

Git flow: phase branch from main; implement; run required checks; commit and push phase; merge with `--no-ff` only after checks pass; push main. GitHub pull requests are optional review wrappers; merges retain phase history.

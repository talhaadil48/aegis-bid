# Implementation and validation ledger

The two root documents are the requirements baseline. Proposed capacity and recovery objectives remain unproven until measured.

| Phase | Scope | Completion gate |
| --- | --- | --- |
| 01 | PostgreSQL schema, ordered engine, fencing, idempotency, allocation | Real PostgreSQL race/retry/cutoff tests; push branch; merge |
| 02 | Authentication, durable pipeline, API, live updates, role dashboards | API authorization and end-to-end tests; frontend build; push branch; merge |
| 03 | Independent verifier, signed evidence, monitoring, chaos, load tooling | Tamper and replay tests; measured workload; push branch; merge |
| 04 | Backup export, isolated restore, Bacula integration, runbooks | Export/restore rehearsal; record actual limits; push branch; merge |

P2 remains a deployment extension: multi-zone load balancers, safely fenced database promotion, independent offsite storage, multi-host 50,000-client benchmarks, and predictive autoscaling. One workstation cannot demonstrate independent failure domains.

Git flow: phase branch from main; implement; run required checks; commit and push phase; merge with `--no-ff` only after checks pass; push main. GitHub pull requests are optional review wrappers; merges retain phase history.

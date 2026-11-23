# Implementation and validation ledger

The two root documents are the requirements baseline. Proposed capacity and recovery objectives remain unproven until measured.

| Phase | Scope | Completion gate |
| --- | --- | --- |
| 01 | PostgreSQL schema, ordered engine, fencing, idempotency, allocation | Real PostgreSQL race/retry/cutoff tests; push branch; merge |
| 02 | Authentication, durable pipeline, API, live updates, role dashboards | API authorization and end-to-end tests; frontend build; push branch; merge |
| 03 | Independent verifier, signed evidence, monitoring, chaos, load tooling | Tamper and replay tests; measured workload; push branch; merge |
| 04 | Backup export, isolated restore, Bacula integration, runbooks | Export/restore rehearsal; record actual limits; push branch; merge |
| 05 | Go gateway, bounded fanout, sharded socket workload | 50,000 simultaneously retained sockets; Go race tests and CI |
| 06 | Physical backups, durable continuous WAL archive, PITR | Local and CI recovery beyond the base backup; matching ledger anchor |
| 07 | Encrypted offsite transport, S3 version pinning, COMPLIANCE retention | Real object-store round trip and database restore; local + CI |
| 08 | Three-zone infrastructure, PostgreSQL/NATS TLS quorum, HA workloads | Real node-loss recovery, cloud schema validation, Kubernetes admission checks, CI |
| 11 | Terminal late-bid admission and legacy queue repair | 29 PostgreSQL/NATS tests; stable CLOSED retry/history; unchanged sealed winners and audit anchor |

The implementation phases and their recorded proofs are in Git history. See `measurements.md` for measured results and `ha-deployment.md` for cloud commissioning. Phase 08 also records an actual remote AWS S3 backup/restore, with keys kept outside the repository and application containers.

Implemented stack: FastAPI API, bounded database pools, scalable Go WebSocket gateway, Python fenced workers and outbox relay, PostgreSQL authority, replicated TLS JetStream, Next.js role views, Prometheus/Grafana, Bacula recovery, physical WAL/PITR, and encrypted locked S3 exports. Redis is unnecessary for this implementation. The baseline race harness remains a controlled in-memory demonstration because the V1 source was not supplied.

Measured: 50,000 sockets held concurrently for 58.01 seconds on one host; real PostgreSQL standby promotion after stopping a worker node; physical PITR recovering decisions absent from the base backup; NATS TLS/quorum; and actual remote AWS S3 restore with verified 30-day COMPLIANCE retention. The socket workload shares a demo identity and is not a proof of 50,000 unique users or simultaneous bids. Kubernetes lab zone labels are simulated; physical AWS zone independence is not claimed from the lab.

External deployment constraint: the configured AWS profile can use S3 but returns AccessDeniedException for EKS management inventory. The three-zone EKS/VPC/NAT/CSI/KMS template and HA application deployment are implemented and validated; launching the actual multi-zone cloud stack needs an appropriately authorized infrastructure role, DNS and registry images. The real S3 repository is physically remote but uses the configured account, not a newly created independently administered account. Those infrastructure distinctions remain explicit.

Still outside these four production extensions: payment settlement, a full legacy-system benchmark, adaptive deadline-based fleet pre-warming, a multi-host/unique-identity 50k benchmark and a real whole-zone outage rehearsal. Submission identity, narrated video and screenshots require the student's own material.

Git flow: phase branch from main; implement; run required checks; commit and push phase; merge with `--no-ff` only after checks pass; push main. GitHub pull requests are optional review wrappers; merges retain phase history.

Late-request fix: an authenticated valid request admitted after the deadline or final close is stored with state CLOSED and an admission outcome containing a reason and timestamp. These are admission receipts outside the sealed bidding ledger; no post-close bid event changes the winners or anchor. Same-payload UUID retries return the existing result, including earlier accepted bids. Reconciliation repairs legacy queued requests on already closed auctions. Terminal POST responses use HTTP 200; pending durable admissions use HTTP 202.

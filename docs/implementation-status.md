# Implementation and validation ledger

The two root documents are the requirements baseline. Proposed capacity and recovery objectives remain unproven until measured.

**Current checkpoint (24 November):** two recorded HTTP-only runs passed the 50,000-distinct-bidder final-window gate, including a worker kill. Subsequent ingress/fanout configuration changes have not reproduced that result consistently: the latest HTTP-only worker trial admitted 42,794 within the window, and the latest combined-live worker trial admitted 30,782. Both failed the workload gate. The 50k successes are historical measured results for their recorded configurations, not a capacity guarantee for the current branch. Phase 13 remains unmerged pending focused diagnosis and regression validation. Large-run experimentation has stopped at this checkpoint; no stress project is running.

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
| 12 | Bounded batched admission, identity lookup and decision commits | Ordered replay, capacity/UUID conflicts, transaction rollback and disconnected-client tests; no capacity claim before stress measurement |
| 13 | Distinct-bidder burst, parallel ordered intake, grouped Go ingress and failure proof | 50,000 distinct users in final 10 seconds: normal HTTP and real worker-SIGKILL runs PASS; signed full replay; combined-live profile tracked separately |

The implementation phases and their recorded proofs are in Git history. See `measurements.md` for measured results and `ha-deployment.md` for cloud commissioning. Phase 08 also records an actual remote AWS S3 backup/restore, with keys kept outside the repository and application containers.

Implemented stack: FastAPI API, bounded database pools, scalable Go WebSocket gateway, Python fenced workers and outbox relay, PostgreSQL authority, replicated TLS JetStream, Next.js role views, Prometheus/Grafana, Bacula recovery, physical WAL/PITR, and encrypted locked S3 exports. Redis is unnecessary for this implementation. The baseline race harness remains a controlled in-memory demonstration because the V1 source was not supplied.

Measured: 50,000 distinct authenticated HTTP bidders with every client write and SQL admission timestamp inside the final ten seconds, zero request errors and a full signed decision/winner replay, both normally and with a worker killed during the burst. These runs use 5,120 pooled HTTP connections and drain queued results after the cutoff; they do not establish 50,000 simultaneous in-flight transactions or all decisions finishing in ten seconds. See [the bidding proof](bidding-proof.md). Also measured: 50,000 shared-identity sockets held concurrently for 58.01 seconds; PostgreSQL standby promotion after stopping a worker node; physical PITR; NATS TLS/quorum; and actual remote AWS S3 restore with verified 30-day COMPLIANCE retention. Kubernetes lab zone labels are simulated; physical AWS zone independence is not claimed from the lab.

External deployment constraint: the configured AWS profile can use S3 but returns AccessDeniedException for EKS management inventory. The three-zone EKS/VPC/NAT/CSI/KMS template and HA application deployment are implemented and validated; launching the actual multi-zone cloud stack needs an appropriately authorized infrastructure role, DNS and registry images. The real S3 repository is physically remote but uses the configured account, not a newly created independently administered account. Those infrastructure distinctions remain explicit.

Still outside these production extensions: payment settlement, a full legacy-system benchmark, adaptive deadline-based fleet pre-warming, a multi-host 50k benchmark and a real whole-zone outage rehearsal. Submission identity, narrated video and screenshots require the student's own material.

Git flow: phase branch from main; implement; run required checks; commit and push phase; merge with `--no-ff` only after checks pass; push main. GitHub pull requests are optional review wrappers; merges retain phase history.

Late-request fix: an authenticated valid request admitted after the deadline or final close is stored with state CLOSED and an admission outcome containing a reason and timestamp. These are admission receipts outside the sealed bidding ledger; no post-close bid event changes the winners or anchor. Same-payload UUID retries return the existing result, including earlier accepted bids. Reconciliation repairs legacy queued requests on already closed auctions. Terminal POST responses use HTTP 200; pending durable admissions use HTTP 202.

Throughput changes retain one serialized decision authority per auction while permitting parallel admission inserts. Go ingress groups up to 512 individual requests with a 100 ms collection ceiling and eight in-flight RPCs per auction. FastAPI verifies each session/role; identity lookup groups use 2 ms and the direct admission route uses 100 ms. SQL sequence reservation and a shared intake barrier permit concurrent inserts; an exclusive worker prefix barrier prevents overtaking uncommitted lower sequences. Decision batches commit at most 512 separate results/events and one latest-version outbox notification. A separate command publication table avoids relay/decision row-lock contention. Queue capacity defaults to 60,000; buffers remain bounded and disconnected waiters do not cancel group work. Globally ordered UUID locks protect cross-auction conflicts. New worker boots use distinct holders and the five-second fenced lease. See [implemented lock and flow details](architecture.md).

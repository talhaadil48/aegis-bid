# Measured local results · 23 November 2026

Machine: Windows 11, Docker Desktop Linux containers; Python 3.13; PostgreSQL 18; NATS 2.11; Next.js 16.4.6; Debian-packaged Bacula 9.6.7. Workstation resources were shared during these tests. These are coursework smoke/drill measurements, not capacity forecasts.

| Experiment | Observed result | Evidence |
| --- | --- | --- |
| HTTP decisions | 30 bids, concurrency 10, 7.96 completed/s, p50 1.162 s, p95 1.538 s, p99 1.753 s, 0 request-error rate | `evidence/load-local.json` and CSV |
| Worker crash | SIGKILL, 20 retries of one request, one accepted request, recovery observed in 2.09 s after explicit restart | `evidence/worker-failure.json` |
| JetStream cluster | Three replicas: publish succeeded with one node down; no false durable acknowledgment after majority loss | `evidence/jetstream-cluster.json` |
| Logical export restore | 20 decisions, 21 events, 3 winners; checksums/replay PASS; DB import + verification 1.74 s | `evidence/recovery-local.json` |
| Bacula backup | Catalog job 1, 4 entries, 39,802 bytes, successful T | `evidence/bacula-console.txt` |
| Bacula restore | Catalog job 2, 4 entries, successful T; restored dump/manifest into alternate directory | `evidence/bacula-console.txt` |
| Restored Bacula database | Counts, hashes and independent winner replay PASS; DB import + verification 1.25 s | `evidence/recovery-bacula.json` and HTML |
| Test suite | 14 passing tests, real PostgreSQL + NATS enabled | Reproduce with README instructions |
| Frontend | Production export builds; npm audit reported zero vulnerabilities after Next.js update | Reproduce with locked npm dependencies |

No 50,000-socket test, multi-host load test, full-site disaster, offsite media loss or measured RPO has been performed. The baseline comparison is an explicitly synthetic race demonstration. Browser rendering was not inspected with an automated browser; build and HTTP smoke tests passed.

## Production extension measurements

The Go gateway retained **50,000 authenticated WebSockets concurrently for a shared 58.01-second interval**, with zero handshake errors. Five generators each requested/retained 10,000 sockets and held for 90 seconds after their individual ramps. Evidence: `evidence/sockets-8be4e979f1bb4723bfcb86fe7a90f37a/`. Sampled gateway memory was about 1.36 GiB; generators about 175 MiB each (`evidence/resources-50k.json`). All containers shared the local 12-CPU, 7.46-GiB Docker host and a demo identity with its socket quota explicitly raised. This supersedes the earlier absence of a local 50k-socket test; it does not establish 50k unique bidders, multi-host capacity, 50k simultaneous bids, or multi-zone resilience.

| Production extension | Actual result | Evidence |
| --- | --- | --- |
| Continuous physical PITR | Base contained 1 decision; archived WAL recovered 2 decisions and 3 events; matching anchor, recovery/verification 3.12 s | `evidence/pitr-local.json` |
| Synchronous PostgreSQL HA | Actual primary worker-container loss; standby promotion and verification 67.21 s; 3 committed decisions retained, stale worker fenced | `evidence/ha-local.json` |
| Authenticated NATS TLS | Certificate verification and credentials succeeded; three-replica stream acknowledged a real publish | `evidence/ha-nats-tls.json` |
| Locked object-store protocol | Retained version deletion denied; corrupted newer index ignored; isolated database PASS | `evidence/offsite-local.json` |
| Real AWS offsite recovery | Private Singapore S3 repository, AES-256-GCM plus server-side encryption, 30-day COMPLIANCE lock, downloaded database PASS; retrieval + verification 1.97 s | `evidence/s3-offsite.json` |
| Infrastructure validation | EKS and S3 CloudFormation templates pass cfn-lint; Kubernetes workload and Barman resources pass actual API-server dry runs | Reproduce with `docs/ha-deployment.md` |

PITR RPO in the controlled drill is the interval between the chosen restore point and injected corruption; it is not a measured full-site/offsite RPO. The remote S3 measurement used a small 20-decision dataset. No EKS compute stack was launched: the available AWS principal denied EKS management calls. All source and report scopes distinguish these limits.

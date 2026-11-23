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

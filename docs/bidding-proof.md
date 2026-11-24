# Final-ten-second bidding proof

The assignment workload is measured separately from idle socket capacity. On 24 November 2026, the local harness passed a normal run and a real worker-SIGKILL run with **50,000 distinct authenticated bidders**, one original HTTP bid per bidder, every client write and every SQL admission timestamp inside the same final ten-second interval, and no request errors, missing records or payload/history mismatches.

## Recorded HTTP results

**Current branch caveat:** the successful measurements below belong to their recorded image/configuration baselines. Later configuration experiments regressed. Trial `bids-016565f97e864027aa719913aed75237` recorded only 42,794 eligible HTTP requests; trial `bids-5bcdf2d89415464281f02b6d75e4a36f` held 50,000 distinct sockets but recorded only 30,782 eligible bids. Both remain FAIL. Consistent current-branch capacity and combined-live 50k bidding remain unproven; the phase is not ready to merge.

| Observation | Normal | Worker killed during bidding |
| --- | ---: | ---: |
| Distinct users / requests | 50,000 / 50,000 | 50,000 / 50,000 |
| Requests written within final 10 seconds | 50,000 | 50,000 |
| SQL admission timestamps within final 10 seconds | 50,000 | 50,000 |
| Request errors / missing IDs / late admissions | 0 / 0 / 0 | 0 / 0 / 0 |
| ACCEPTED / REJECTED by recorded decision time at cutoff | 2,260 / 17,708 | 3,198 / 6,530 |
| Still QUEUED by that timestamp calculation at cutoff | 30,032 | 40,272 |
| Final ACCEPTED / REJECTED / QUEUED | 14,730 / 35,270 / 0 | 18,290 / 31,710 / 0 |
| Last recorded decision after cutoff | 13.335 s | 8.913 s |
| HTTP ingress latency p50 / p95 / p99 | 0.369 / 1.108 / 1.515 s | 0.326 / 0.734 / 0.853 s |
| SQL admission-to-recorded-decision p50 / p95 / p99 | 6.561 / 13.320 / 14.091 s | 8.743 / 9.686 / 9.804 s |
| Signed decisions / events / winners | 50,000 / 50,001 / 20 | 50,000 / 50,001 / 20 |
| Full SQL histories checked | 50,000 | 50,000 |
| Owner HTTP histories / stable-UUID retries sampled | 64 / 64 | 64 / 64 |
| Offline original client CSV to signed ledger replay | PASS | PASS |

Normal: [complete summary](evidence/bids-6a3415630f674d6cbeb45f1b121ccdf6/summary.json). Worker failure: [complete summary](evidence/bids-93aedc3e13254c52ab5712e0716b7201/summary.json) and [actual kill/restart observation](evidence/bids-93aedc3e13254c52ab5712e0716b7201/worker-crash.json).

The differing accepted counts are expected: batches reserve intake sequences according to server arrival, not the load generator's ascending amount schedule. Accepted means the bid passed the global increment rule when processed; it does not mean that bidder ultimately won stock. Each independent signed replay recomputes those decisions and the final 20 stock-limited winners.

## What the timings prove

The harness seeds 50,000 distinct database users and issues valid HS256 sessions before measurement. It does not benchmark password hashing or login throughput. Five generators offer their original requests over nine seconds inside the final ten-second window, using up to 1,024 HTTP connections each: **5,120 pooled HTTP connections**, not 50,000 simultaneous in-flight HTTP transactions. The mean offered rate is approximately 5,556 bids/s over the nine-second spread, with 50,000 offers in the ten-second window; this is an admission workload, not a claim of 5,000 final decisions/s.

Client HTTP tracing records when the request was written. PostgreSQL stamps eligibility with `clock_timestamp()` inside the admission transaction; HTTP acknowledgment follows its commit. An admission timestamp is not a measurement of the precise WAL-flush or MVCC-visibility instant. Similarly, `bid_decisions.committed_at` is a database-generated row timestamp inside the decision transaction. The cutoff counts above are reconstructed from those recorded timestamps, not a proof that each batch was already externally visible at that exact instant. The saved SQL timeline separately records observed committed states at roughly one-second intervals.

Eligible queued requests remain eligible after the deadline. The worker drains them before final allocation; therefore all 50,000 admissions within the window does **not** mean all 50,000 final results were ready by its end. The recorded backlog and drain time are part of the result.

Both HTTP runs used the same application image `sha256:3f2a60bafb1d846dc89635de7ff513137df4162613979462f7adab06474d0fdc`, tools image `sha256:17d98bef236c0681e3e9133afc64b4fe20c2aca14c4f5f416fed47327370c137`, six API processes and the source baseline `f607529`. All services and generators shared one Docker Desktop Linux VM: 12 CPUs and 8,009,699,328 bytes (7.46 GiB). PostgreSQL `fsync`, `synchronous_commit` and `full_page_writes` remained on.

## Failure and terminal-result checks

The worker-failure harness sends a real Docker SIGKILL about four seconds into bidding, confirms the process stopped with exit code 137, explicitly restarts it after a pause, and continues offering requests. It records a pre-crash event checkpoint and lease, verifies that checkpoint survived, requires the replacement worker's epoch to increase, and tries the old identity/epoch to prove fencing. This is actual worker-process failure, not database-primary failure at 50,000-bid load. The separate small-dataset PostgreSQL-primary failover drill retains its own scope.

Every request is matched to its original bidder UUID and integer-cent amount. All SQL final states and histories are checked; 64 authenticated owner histories and same-UUID HTTP retries are sampled. The signed export contains every bid decision and one close event. Offline verification matches every original client request to its signed pseudonymous event, checks eligibility/order/rules/hash links, and recomputes winners. Altered winners must fail verification. A newly submitted post-close UUID must return CLOSED without changing the sealed anchor or winners.

The per-run public key is included for reproducible signature verification. The original signing key remains private under the ignored cache directory. A downloaded export and adjacent public key are not an independently authenticated institutional trust anchor; distribute/pin the public key separately for stronger provenance.

## Reproduce without cloud resources

Run from the repository root with Docker and installed `requirements.lock` dependencies. The harness creates a uniquely named Compose project, isolated database and volumes, private generated credentials, and safe evidence artifacts. It removes only its own isolated containers/volumes afterward. It does not call AWS.

```powershell
.venv\Scripts\python.exe -m scripts.bid_stress --bidders 50000 --shards 5 --no-sockets
.venv\Scripts\python.exe -m scripts.bid_stress --bidders 50000 --shards 5 --no-sockets --fault worker --skip-build
.venv\Scripts\python.exe -m scripts.verify_bid_stress docs/evidence/bids-6a3415630f674d6cbeb45f1b121ccdf6
.venv\Scripts\python.exe -m scripts.verify_bid_stress docs/evidence/bids-93aedc3e13254c52ab5712e0716b7201
```

Omit `--no-sockets` to require a distinct authenticated WebSocket for every bidder throughout the combined workload. `--skip-build` uses existing image tags; use it only after both builds finish. Each summary records the actual image IDs used. HTTP-only PASS is not a combined-live PASS, and a previously successful shared-identity socket experiment is not a distinct-user bidding proof.

## Failed trials remain evidence

The corrected failure harness restarts only the previously recorded worker container with `docker start`, and checks that the migration container's start timestamp does not change. Earlier `docker compose start worker` commands could restart the completed migration dependency; PostgreSQL logs from trial `bids-664d0944693c427b9a2d9612ab0766b8` show admission transactions deadlocking against repeated migration DDL. Removing that test defect did not by itself resolve the combined-live performance gap. Memory, fanout cadence and service isolation hypotheses must therefore not be presented as established root causes.

Failed ramp/setup runs and failed deadline experiments remain under `docs/evidence/bids-*`. Earlier bottlenecks included globally serialized authentication, Python middleware/dispatch overhead, per-row SQL overhead, auction-row intake serialization and command-publication contention. The near-pass `bids-a7f0d0da807543a9801cd0c9fb79b7a1` admitted 49,998 users with no late admissions but had two transport errors; it remains FAIL. The first combined worker run `bids-8901da1775f343a6b9bce28a38f3451d` held all 50,000 live connections but admitted only 22,584 before cutoff and remains FAIL. Successful HTTP-only runs do not relabel either trial.

This evidence establishes a controlled local result, not a multi-host capacity forecast, a physical whole-zone outage, a production AWS deployment, payment settlement, independently administered backups or continuous production offsite PITR/RPO.

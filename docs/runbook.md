# Operations runbook

## Startup and observability

Use the README quick start. `docker compose --env-file .env -f infra/compose.yaml ps` must show the database healthy and API/worker/relay running. `/health` verifies the database only; inspect worker logs, leases and queue depth separately. `docker compose --env-file .env -f infra/compose.yaml --profile monitoring up -d` starts Prometheus at port 59090 and Grafana at 53000. Set `GRAFANA_PASSWORD` first. Monitoring is private to loopback.

## Test-only chaos

Set `ENABLE_CHAOS=true` in `.env`, recreate the API, and explicitly export it into the shell running `python -m scripts.chaos_controller`. The controller executes fixed Compose service operations; the API has no Docker socket. Pause/resume affects the SQL worker loop directly. Kill/restart requests remain PENDING until the host controller runs. Inspect `/v1/admin/incidents` for the incident timeline. Stop the controller and disable chaos afterward. Cache-loss is not offered until a Redis projection is installed; this implementation reads the authority directly.

After a worker kill, inspect the restart count, current lease and epoch. Wait for the old five-second lease to expire. Queued requests must resolve using their original request IDs. Compare committed decisions and winner replay before and after. A resolved process command alone does not prove auction recovery.

## Three-node JetStream

Use `-f infra/compose.yaml -f infra/compose.cluster.yaml` on a fresh isolated Compose project. The overlay configures three servers and stream replication=3. Existing single-replica streams require an explicit supported stream update; changing an environment variable does not migrate existing replicas. Inspect stream info before testing. Never remove existing data volumes just to switch modes.

SQL is the authoritative admission journal. A SQL commit allows QUEUED even if JetStream is temporarily unavailable; relay retries publication. This deliberately differs from a JetStream-only admission design. Do not interpret QUEUED as a JetStream quorum acknowledgment. Losing SQL authority stops admission; restoring SQL pending requests allows reconciliation without a matching NATS snapshot.

## Independent audit

Run `python -m scripts.generate_audit_key <directory-outside-repo>`. Mount the private key read-only into the API and set `AUDIT_SIGNING_KEY` to that path; retain the public key separately. Download the auditor evidence JSON and run `python -m aegis.verifier auction.json --trusted-key <trusted-public.pem>`. PASS requires a verified signature plus replay invariants. Unsigned evidence is INCOMPLETE. Bid receipt hashes refer to the signed auction history. A malicious original signer remains outside this evidence guarantee.

## Workload evidence

Create a fresh disposable auction. Set `DEMO_PASSWORD` in the shell, then `python -m scripts.run_load --auction <uuid> --bids 30 --concurrency 10`. JSON/CSV in `docs/evidence/` record actual latency, throughput, errors, machine and commit. Rate limits are deliberately active. This is a single-account HTTP workload; it does not measure socket capacity. `python -m scripts.compare_baseline` demonstrates a controlled read/modify/write race in memory and is explicitly not an old-system benchmark.

## Incident handling

For database loss or corruption, stop application writers and preserve logs. Restore a verified export into a newly created isolated database; never overwrite the current authority. Verify checksums, independently replay auctions, reconcile pending intake and document missing acknowledged decisions. An operator must decide whether recovered data can become authoritative. Do not automatically promote an unfenced PostgreSQL server.

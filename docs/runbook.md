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

For the assignment-scale workload use `python -m scripts.bid_stress --bidders 50000 --shards 5 --no-sockets`. Add `--fault worker` for an actual kill during bidding; omit `--no-sockets` to require all distinct users' live sockets as well. This creates isolated resources and credentials automatically and does not access AWS. Do not run it during a short presentation. Verify an existing saved run with `python -m scripts.verify_bid_stress docs/evidence/bids-<run-id>`. The complete methods, recorded accepted/rejected/queued counts and scope are in [bidding-proof.md](bidding-proof.md).

## Ordered-intake upgrade and ingress isolation

The parallel-intake migration and new worker must be rolled out together. An old worker does not take the new admission barrier. Stop API, worker, relay and Go ingress processes before migrating an existing database; preserve all data volumes. Back up using the existing runbook first when upgrading a non-disposable installation. Existing Kubernetes operators must suspend old writers before running the migration Job and replace them with the new image afterward; do not leave old and new workers running across this migration.

Set a new independent random `ADMISSION_SERVICE_KEY` of at least 32 characters in the private runtime environment, shared by FastAPI and the Go admission service. Existing Kubernetes runtime secrets need an `admission-key` entry. Keep it out of Git, client code, screenshots and command output. The ordinary Python-only Compose layout can still use direct FastAPI admission; the scale overlay uses separate Go admission and live services so fanout cannot monopolize the bid ingress process.

For an existing local Compose installation, after preparing the key:

```powershell
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.scale.yaml stop web gateway admission api worker relay
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.scale.yaml build
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.scale.yaml up -d postgres nats1
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.scale.yaml run --rm migrate
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.scale.yaml up -d
```

Do not use `down --volumes` for this upgrade. `/v1/auctions` goes through the admission service (other auction reads are transparently forwarded to FastAPI); `/v1/live/` goes to the independent live gateway. The hidden internal endpoint authenticates the service key before parsing and verifies every supplied session/role. PostgreSQL JIT is disabled for this short-transaction profile; durability remains enabled. Confirm the local dashboard, owner histories, a same-UUID retry, terminal post-close requests and worker recovery after upgrading.

## Incident handling

For database loss or corruption, stop application writers and preserve logs. Restore a verified export into a newly created isolated database; never overwrite the current authority. Verify checksums, independently replay auctions, reconcile pending intake and document missing acknowledged decisions. An operator must decide whether recovered data can become authoritative. Do not automatically promote an unfenced PostgreSQL server.

# Production extension deployment and proof

This runbook separates deployable mechanisms from measured infrastructure. A one-host result does not establish independent zones or offsite survival.

The complete multi-zone commissioning sequence is in [ha-deployment.md](ha-deployment.md), including the three-zone EKS foundation, TLS, synchronous PostgreSQL, three-node NATS, ingress, workload rendering and continuous object-store recovery.

## Scalable realtime gateway and socket workload

`docker compose --env-file .env -f infra/compose.yaml -f infra/compose.scale.yaml up -d --build gateway web` enables the Go gateway and routes `/v1/live/` through it. The gateway fetches one authoritative snapshot per active auction per second and shares prepared frames among subscribers. Each connection has a single bounded update slot, a read limit, ping/pong expiry and a write deadline. API remains the authenticated decision/admission authority. Session identity is verified through the API and cached for at most 30 seconds. Snapshot source failure closes subscribers after three failed polls so reconnect can reconcile.

Default per-user socket quota is 10; total/per-auction quota is 60,000 per gateway process. For an **isolated socket-capacity test only**, set `MAX_USER_CONNECTIONS=60000` in the invoking shell and recreate gateway. Do not deploy that quota as a production anti-abuse policy. Tests sharing a demo identity establish socket capacity, not unique bidder capacity.

Run `python -m scripts.socket_capacity --connections 100 --shards 1 --hold 30`, then 1,000, 10,000 and, if resources permit, 50,000 with five shards. Export `DEMO_PASSWORD` into the shell. Results contain each shard's actual opened and retained connections, handshake latency, failure counts and timestamps. The aggregator rejects missing reports, duplicate shards, mixed runs, disjoint hold intervals and dropped sockets. Five source containers avoid exhausting one source IP's ephemeral port range. Results identify the shared host and explicitly exclude bid throughput.

On independent generator hosts, run `/usr/local/bin/load -url wss://<public-host>/v1/live/auctions/<id> -connections 10000 -ramp 50 -hold 120s -output shard.json` from the realtime image, passing `WS_COOKIE`, a common `RUN_ID`, and a unique `SHARD_ID` through a protected environment. Collect reports and use `scripts.socket_capacity.aggregate` with required=50000 and a common hold of at least 30 seconds. Every generator must read real auction snapshots. Match aggregate reports against gateway metrics and resource telemetry; do not sum non-overlapping peak counts.

Reference: [Gorilla concurrency and control frames](https://pkg.go.dev/github.com/gorilla/websocket).

## Continuous WAL archiving and physical PITR

`infra/compose.pitr.yaml` is a separate recovery deployment, with unique source, base-backup, WAL and restore volumes. It never mounts the application database volume. Archive publication fsyncs and atomically hard-links completed WAL segments; a conflicting file must compare byte-for-byte or archiving fails. `archive_timeout=60s` limits idle-segment rotation; monitor actual archive lag and storage availability rather than assuming a 60-second RPO.

Run `python -m scripts.rehearse_pitr` with `POSTGRES_PASSWORD` exported. Each run creates a new Compose project, initializes the ledger, takes and verifies `pg_basebackup`, commits additional decisions, records a named recovery point, deliberately corrupts only that disposable source ledger, waits for WAL archival, and boots an isolated recovery target. It independently compares the recovered ledger to the saved pre-corruption evidence. Services stop afterward; data volumes are retained for inspection.

For an operational recovery, set `BASE_NAME` to a completed backup and exactly one of `RECOVERY_TARGET_NAME` or timezone-aware `RECOVERY_TARGET_TIME`. Use a **new project/empty restore volume** and start `recovered` with the recovery profile. The restore script refuses a populated target, runs `pg_verifybackup`, configures `restore_command`, and creates `recovery.signal`. PostgreSQL refuses recovery if the selected target cannot be reached. Automatic promotion is confined to this isolated recovery service; it does not reroute application traffic. Preserve all WAL through the selected target and all timeline history files. Archive retention must account for every retained base backup.

The PITR profile's archive is still local. Couple it with the independent offsite shipping process below before describing it as protection from host loss. Protect Bacula's Catalog/configuration and the physical backup/WAL volumes independently. The restore report's RTO covers database creation/replay/verification only; a full-site exercise must also time media retrieval, credential recovery, application startup and validation.

References: [PostgreSQL 18 physical backups](https://www.postgresql.org/docs/18/app-pgbasebackup.html), [continuous archiving and PITR](https://www.postgresql.org/docs/18/continuous-archiving.html).

## Independent encrypted offsite repository

Deploy `infra/offsite/bucket.cloudformation.json` in a **separate backup account and region** using an existing authorized cloud identity. It creates a private, versioned, encrypted S3 bucket with 30-day COMPLIANCE retention and denies insecure transport. The stack retains the bucket on deletion. Apply the writer/restore policies to separate backup-host identities after replacing the bucket placeholder. No application pod receives either credential. Real COMPLIANCE retention cannot be shortened even by the bucket administrator; choose the retention policy before uploading.

On the independent backup host install `requirements.lock`, `requirements-backup.lock` and this package. Provide `BACKUP_BUCKET`, optional HTTPS `BACKUP_ENDPOINT`, AWS credentials through the SDK's profile/workload identity chain, and an independently protected `BACKUP_ENCRYPTION_KEY` containing 64 random hex digits. The key must be recoverable outside both the application and object repository. Preserve upload receipt files with the backup Catalog in the independent domain; they pin exact object versions.

`python -m scripts.offsite_backup upload <completed-export-directory> --receipt <new-receipt.json>` validates source hashes, streams AES-256-GCM encryption, requests COMPLIANCE retention with upload checksums, and reads back version and retention metadata before recording success. The encrypted authenticated index is published last. Incomplete uploads never publish a valid snapshot index. Each file is context-bound to its object key. Source files above the object store's single-PUT limit require splitting or a multipart extension; ordinary PostgreSQL relation/WAL files fit below that limit.

`python -m scripts.offsite_backup restore <new-empty-directory> --receipt <receipt.json>` fetches exact versions, verifies ciphertext hashes and authentication tags, rejects unsafe paths/overwrites and verifies plaintext checksums. Run the existing isolated database restore/verifier against the downloaded export before authorizing recovered traffic. A corrupt newer version or a delete marker cannot change the pinned version in the receipt. Maintain a separate trusted copy of receipts and keys.

The systemd service in `infra/offsite/` scans completed exports every 30 seconds and writes durable receipts only after upload/retention verification. Run it on the independent backup host, stage completed physical base/WAL bundles and logical exports through an authenticated transfer, and monitor `last-success.json` plus actual recovery coverage. Continuous production WAL streaming is configured through the CloudNativePG object-store plugin in the HA deployment; do not equate a recent logical export with continuous PITR.

`python -m scripts.rehearse_offsite <completed-export-directory>` builds the upstream S3-compatible test fixture from its pinned source release, checks COMPLIANCE deletion denial, intentionally writes a newer corrupt index, restores the pinned original and verifies a fresh database. This is a protocol rehearsal on the same host, not physical offsite proof. Real offsite loss testing needs the independent account/host and its credentials.

References: [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html), [S3 upload checksums and retention](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html).

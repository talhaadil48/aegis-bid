# Backup and isolated recovery

## Consistent export

Run `python -m scripts.backup_export backup-staging/<unique-run>`. Use PostgreSQL client tools matching the source server's major version. The exporter holds a read-only repeatable-read transaction, uses `pg_export_snapshot()` for pg_dump, and counts records under the same snapshot. Manifest hashes cover the custom-format dump. The job is EXPORTED, never BACULA_COMPLETED, until actual Catalog evidence is imported.

Manifests include schema version, checkpoint, counts and per-auction sequence positions. This is logical snapshot recovery. NATS stream snapshots and continuous WAL/PITR are not part of this local export; pending SQL intake is the reconciliation source. A hash stored next to a dump protects against accidental corruption, not coordinated malicious replacement. Keep a copy of manifest checksums in a protected independent location.

## Bacula rehearsal

Start the Bacula deployment described in README. It uses Debian's packaged Bacula 9.6.7 with a PostgreSQL Catalog; configs are validated at startup. The private profile exposes no host ports. Connect with:

```sh
docker compose --env-file .env -f infra/compose.bacula.yaml exec bacula bconsole
```

In `bconsole`:

```text
status dir
run job=AegisBidBackup yes
wait
list jobs
messages
restore jobid=<successful-backup-id> all done yes
wait
list jobs
```

Inspect JobStatus `T`, bytes and file counts for both backup and restore. The FileSet covers prepared `/staging` exports. Restore writes only to `/restore`, mounted at repository `restore-output/`. Backup media and Catalog have separate named volumes. Their host is still shared with the application: this proves the mechanics, not independent disaster survival.

Record actual Catalog evidence with `python -m scripts.record_bacula restore-output/staging/<run> --job-id <backup-id>`. It queries Catalog, rejects failed/non-backup jobs and records the measured result for the admin dashboard. Do not modify a saved manifest to insert a job ID after Bacula backed it up.

## Verify restored material

`python -m scripts.restore_sandbox restore-output/staging/<run> --output docs/evidence/recovery-bacula` verifies checksums **before** creating a database, creates a random new `aegis_restore_*` database, imports with `pg_restore --exit-on-error`, independently replays auction events and checks snapshot counts/positions and winners. It emits JSON and HTML certificates and records a recovery run. Existing databases are never dropped or overwritten. Optional `RESTORE_ADMIN_URL` chooses the isolated server; use a separate host for a genuine DR exercise.

The recorded `rto_s` covers database creation, import and verification only. It excludes operator response, Bacula media retrieval and rebuilding the site. `rpo_s` remains null without a real failure timestamp. Report these limits alongside every certificate. A PASS is limited to the restored dataset and cannot establish site-wide RPO/RTO.

## Protect the backup control plane

Before relying on this setup, preserve the Bacula Catalog (`pg_dump -Fc bacula`), `/etc/bacula` configuration, storage volume index, deployment versions and encryption/signing keys on a separately protected host. Configurations contain passwords; do not commit or publish them. Restore control-plane metadata in a clean network before attempting media recovery. The template `.conf` files in Git contain placeholders only.

For the proposed production extension, add base backups, unbroken WAL archiving, offsite transfer, PITR rehearsals, key recovery and fenced PostgreSQL promotion. No local snapshot demonstration substitutes for those mechanisms.

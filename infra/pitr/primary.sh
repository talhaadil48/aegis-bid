#!/bin/bash
set -euo pipefail
mkdir -p /wal
chown postgres:postgres /wal
exec docker-entrypoint.sh postgres -c wal_level=replica -c archive_mode=on \
  -c 'archive_command=/opt/aegis-pitr/archive-wal.sh "%p" "%f"' \
  -c archive_timeout=60s -c max_wal_senders=10 -c max_replication_slots=10

#!/bin/bash
set -euo pipefail
printf 'host replication all 0.0.0.0/0 scram-sha-256\n' >> "$PGDATA/pg_hba.conf"

#!/bin/bash
set -euo pipefail
: "${BASE_NAME:?Unique BASE_NAME required}"
[[ "$BASE_NAME" =~ ^base-[a-f0-9]{32}$ ]] || exit 1
mkdir -p /backups
chown postgres:postgres /backups
[[ ! -e "/backups/$BASE_NAME" ]] || { echo 'Refusing to overwrite base backup'; exit 1; }
gosu postgres pg_basebackup -h primary -U "$POSTGRES_USER" -D "/backups/$BASE_NAME" \
  -Fp -X stream --checkpoint=fast --manifest-checksums=SHA256
gosu postgres pg_verifybackup "/backups/$BASE_NAME"

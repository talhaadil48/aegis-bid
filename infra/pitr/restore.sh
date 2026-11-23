#!/bin/bash
set -euo pipefail
: "${BASE_NAME:?BASE_NAME required}"
[[ "$BASE_NAME" =~ ^base-[a-f0-9]{32}$ ]] || exit 1
[[ -d "/backups/$BASE_NAME" ]] || exit 1
[[ -z "$(find "$PGDATA" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]] || { echo 'Restore target is not empty'; exit 1; }
[[ -n "${RECOVERY_TARGET_NAME:-}" || -n "${RECOVERY_TARGET_TIME:-}" ]] || { echo 'Recovery target required'; exit 1; }
[[ -z "${RECOVERY_TARGET_NAME:-}" || -z "${RECOVERY_TARGET_TIME:-}" ]] || { echo 'Choose one recovery target'; exit 1; }
pg_verifybackup "/backups/$BASE_NAME"
mkdir -p "$PGDATA"
cp -a "/backups/$BASE_NAME/." "$PGDATA/"
printf "restore_command = 'cp /wal/%%f %%p'\nrecovery_target_action = 'promote'\narchive_mode = 'off'\n" >> "$PGDATA/postgresql.auto.conf"
if [[ -n "${RECOVERY_TARGET_NAME:-}" ]]; then
  [[ "$RECOVERY_TARGET_NAME" =~ ^aegis_[a-f0-9]{32}$ ]] || exit 1
  printf "recovery_target_name = '%s'\n" "$RECOVERY_TARGET_NAME" >> "$PGDATA/postgresql.auto.conf"
else
  [[ "$RECOVERY_TARGET_TIME" =~ ^[0-9TZ:+.\ -]+$ ]] || exit 1
  printf "recovery_target_time = '%s'\n" "$RECOVERY_TARGET_TIME" >> "$PGDATA/postgresql.auto.conf"
fi
touch "$PGDATA/recovery.signal"
chown -R postgres:postgres "$PGDATA"
chmod 700 "$PGDATA"
exec docker-entrypoint.sh postgres

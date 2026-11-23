#!/bin/bash
set -euo pipefail
: "${BACULA_PASSWORD:?Set a URL-safe random BACULA_PASSWORD}"
[[ "$BACULA_PASSWORD" =~ ^[A-Za-z0-9_-]{24,}$ ]] || { echo 'Use 24+ URL-safe password characters'; exit 1; }
mkdir -p /run/bacula /var/log/bacula /volumes /restore /var/lib/bacula
for name in bacula-dir bacula-fd bacula-sd bconsole; do
  sed "s/__SECRET__/$BACULA_PASSWORD/g" "/opt/aegis-bacula/$name.conf" > "/etc/bacula/$name.conf"
done
chmod 600 /etc/bacula/*.conf
pg_ctlcluster 15 main start
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='bacula'" | grep -q 1; then
  runuser -u postgres -- psql -c "CREATE ROLE bacula LOGIN PASSWORD '$BACULA_PASSWORD';"
  runuser -u postgres -- createdb -O bacula bacula
fi
if ! runuser -u postgres -- psql -d bacula -tAc "SELECT 1 FROM information_schema.tables WHERE table_name='version'" | grep -q 1; then
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d bacula -f /usr/share/dbconfig-common/data/bacula-director-pgsql/install/pgsql
  runuser -u postgres -- psql -d bacula -c 'GRANT ALL ON ALL TABLES IN SCHEMA public TO bacula; GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO bacula;'
fi
bacula-dir -t -c /etc/bacula/bacula-dir.conf
bacula-sd -t -c /etc/bacula/bacula-sd.conf
bacula-fd -t -c /etc/bacula/bacula-fd.conf
bacula-sd -f -c /etc/bacula/bacula-sd.conf &
bacula-fd -f -c /etc/bacula/bacula-fd.conf &
exec bacula-dir -f -c /etc/bacula/bacula-dir.conf

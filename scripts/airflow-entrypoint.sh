#!/usr/bin/env bash
set -euo pipefail

# Standalone mode generates a random admin password on every start.
# We create a fixed admin user first, then run scheduler + webserver instead.
ADMIN_USER="${_AIRFLOW_WWW_USER_USERNAME:-admin}"
ADMIN_PASS="${_AIRFLOW_WWW_USER_PASSWORD:-admin}"
ADMIN_EMAIL="${_AIRFLOW_WWW_USER_EMAIL:-admin@example.com}"

airflow db migrate

if airflow users list 2>/dev/null | awk -F'|' 'NR>2 {gsub(/ /,"",$2); if ($2=="'"$ADMIN_USER"'") found=1} END {exit !found}'; then
  airflow users delete -u "$ADMIN_USER"
fi

airflow users create \
  --username "$ADMIN_USER" \
  --password "$ADMIN_PASS" \
  --firstname Admin \
  --lastname User \
  --role Admin \
  --email "$ADMIN_EMAIL"

echo "Airflow login: ${ADMIN_USER} / ${ADMIN_PASS}"

airflow scheduler &
exec airflow webserver

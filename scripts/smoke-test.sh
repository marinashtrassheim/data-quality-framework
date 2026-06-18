#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Waiting for Airflow (http://localhost:8080/health)..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
    echo "    Airflow is up (${i}s)"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "ERROR: Airflow did not become healthy in time"
    docker logs airflow --tail 40
    exit 1
  fi
  sleep 2
done

echo "==> Ensuring DAG is unpaused..."
docker exec airflow airflow dags unpause incoming_quality_pipeline >/dev/null

echo "==> Running generator (200 files, ~2 min)..."
docker compose --profile tools up generator --abort-on-container-exit

echo "==> Waiting for DAG to process incoming/ (~90s)..."
sleep 90

echo "==> Results"
docker exec airflow airflow dags list-runs -d incoming_quality_pipeline 2>/dev/null | head -6

docker run --rm --network data-quality-framework_data-quality --entrypoint /bin/sh minio/mc -c '
  mc alias set local http://minio:9000 minioadmin minioadmin >/dev/null
  echo "MinIO counts:"
  echo "  incoming:  $(mc ls local/data-quality/incoming/ --recursive 2>/dev/null | wc -l | tr -d " ")"
  echo "  processed: $(mc ls local/data-quality/processed/ --recursive 2>/dev/null | wc -l | tr -d " ")"
  echo "  failed:    $(mc ls local/data-quality/failed/ --recursive 2>/dev/null | wc -l | tr -d " ")"
  echo "  data_docs: $(mc ls local/data-quality/data_docs/ --recursive 2>/dev/null | wc -l | tr -d " ")"
'

EMAILS=$(curl -sf http://localhost:8025/api/v2/messages | python3 -c "import sys,json; print(json.load(sys.stdin).get('total',0))" 2>/dev/null || echo "?")
echo "  mailhog emails: $EMAILS"

echo ""
echo "Done. Open:"
echo "  Airflow:  http://localhost:8080  (admin / admin)"
echo "  MinIO:    http://localhost:9001  (minioadmin / minioadmin)"
echo "  Mailhog:  http://localhost:8025"

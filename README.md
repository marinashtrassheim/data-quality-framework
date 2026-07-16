# Data Quality Framework

Batch data quality pipeline for JSON transaction files in MinIO, orchestrated by Airflow.

Incoming files are checked with **Soda Core** (fast structural rules), then **Great Expectations** (value and format rules). Failures go to `failed/` and trigger a batch email; successes go to `processed/date=.../` with GE Data Docs HTML stored in `data_docs/`.

## Architecture

```
Generator → MinIO (incoming/) → Airflow DAG → Soda → GE → processed/ | failed/
                                      ↓
                                   Mailhog (failure emails)
```

| Layer | Role | Examples |
|-------|------|----------|
| Soda | Null checks, row count | `missing_count(user_id) = 0` |
| Great Expectations | Ranges, formats, enums | `amount` between 0–10000, `event_time` format |

The generator marks ~30% of files as invalid (configurable via `GENERATOR_INVALID_RATIO`).

## Quick start

**Prerequisites:** Docker, Docker Compose

Run these two steps in order, from a clean state (no leftover containers from a previous run):

```bash
# 1. Start infrastructure and wait for Airflow to report "healthy" (not just "running") —
#    this can take 30-60s: DB migration + admin user creation + scheduler/webserver startup.
docker compose up -d minio mailhog airflow
docker compose ps   # re-run until the airflow row shows "healthy"

# 2. Full end-to-end test (generator + wait for DAG)
bash scripts/smoke-test.sh
```

> ⚠️ `scripts/smoke-test.sh` does **not** start the stack — it only waits on an already-running
> `airflow` container. If you see `No such container: airflow` or `Airflow did not become
> healthy in time`, the stack isn't up (e.g. you ran `docker compose down` since step 1) —
> re-run step 1 before running the script again.

Once healthy, the UI is at http://localhost:8080 (admin / admin).

**Manual generator run** (without the smoke test):

```bash
docker compose --profile tools up generator
```

## Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Airflow | http://localhost:8080 | admin / admin |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| MinIO API | http://localhost:9000 | minioadmin / minioadmin |
| Mailhog | http://localhost:8025 | — |

## Project layout

```
├── airflow/Dockerfile       # Airflow image with GE + Soda baked in
├── common/                  # BatchProcessor, MinIO client, email, settings
├── dags/                    # Airflow DAG (runs every minute)
├── generator/               # Synthetic JSON producer
├── soda/checks.yml          # SodaCL rules
├── scripts/                 # Entrypoint and smoke test
└── docker-compose.yaml
```

## Email behavior

One email is sent **per DAG run** when that run has failures — not per generator batch. The DAG runs every minute and processes everything in `incoming/` at that moment. A full smoke test (200 files over ~2 minutes) typically produces **2 failure emails**.

Data Docs for successful files are stored in MinIO under `data_docs/` (preview via MinIO Console).

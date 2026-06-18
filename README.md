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

```bash
# Start infrastructure
docker compose up -d minio mailhog airflow

# Wait until Airflow is healthy (~15s), then open UI
open http://localhost:8080   # admin / admin

# Full end-to-end test (generator + wait for DAG)
bash scripts/smoke-test.sh
```

**Manual generator run:**

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

## Local Python setup (optional, for IDE)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` if you run components outside Docker.

## Email behavior

One email is sent **per DAG run** when that run has failures — not per generator batch. The DAG runs every minute and processes everything in `incoming/` at that moment. A full smoke test (200 files over ~2 minutes) typically produces **2 failure emails**.

Data Docs for successful files are stored in MinIO under `data_docs/` (preview via MinIO Console).

## Push to GitHub

```bash
git remote add origin git@github.com:marinashtrassheim/-data-quality-framework.git
git push -u origin main
```

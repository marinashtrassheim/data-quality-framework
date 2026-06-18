
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from common.batch_processor import build_processor

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "data-quality",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}


def process_incoming_batch(**context) -> dict:
    processor = build_processor()
    summary = processor.process_batch()
    logger.info("DAG run summary: %s", summary)
    return summary


with DAG(
    dag_id="incoming_quality_pipeline",
    default_args=DEFAULT_ARGS,
    description="Batch data quality checks for JSON files in MinIO incoming/",
    schedule_interval="* * * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    is_paused_upon_creation=False,
    max_active_runs=1,
    tags=["data-quality", "minio", "soda", "great-expectations"],
) as dag:
    process_batch = PythonOperator(
        task_id="process_incoming_batch",
        python_callable=process_incoming_batch,
        provide_context=True,
        execution_timeout=timedelta(minutes=10),
    )

import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import great_expectations as gx
import pandas as pd
from great_expectations.core import ExpectationSuite
from great_expectations.expectations.core import (
    ExpectColumnPairValuesAToBeGreaterThanB,
    ExpectColumnValuesToBeBetween,
    ExpectColumnValuesToBeInSet,
    ExpectColumnValuesToBeUnique,
    ExpectColumnValuesToMatchStrftimeFormat,
    ExpectColumnValuesToNotBeNull,
)
from great_expectations.render.renderer.page_renderer import ValidationResultsPageRenderer
from great_expectations.render.view.view import DefaultJinjaPageView
from great_expectations.self_check.util import build_pandas_validator_with_data
from soda.scan import Scan

from common.email_notifier import EmailNotifier
from common.minio_client import MinIOClient
from common.settings import AppSettings

logger = logging.getLogger(__name__)

EVENT_TIME_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})")
DEFAULT_SODA_TABLE = "transactions"


class ValidationFailedError(Exception):
    def __init__(self, stage: str, failed_checks: List[str], details: Optional[Dict[str, Any]] = None):
        self.stage = stage
        self.failed_checks = failed_checks
        self.details = details or {}
        super().__init__(f"{stage} failed: {failed_checks}")


class BatchProcessor:
    """Processes JSON files from MinIO: Soda first, then Great Expectations."""

    def __init__(
        self,
        settings: AppSettings,
        minio_client: MinIOClient,
        email_notifier: EmailNotifier,
    ):
        self.settings = settings
        self.minio = minio_client
        self.email = email_notifier

    def list_incoming_files(self) -> List[str]:
        prefix = f"{self.settings.incoming_prefix.rstrip('/')}/"
        keys = self.minio.list_objects(prefix=prefix)
        return sorted(key for key in keys if key.endswith(".json"))

    def process_batch(self) -> Dict[str, Any]:
        files = self.list_incoming_files()
        summary: Dict[str, Any] = {
            "total_files": len(files),
            "processed": 0,
            "failed": 0,
            "errors": [],
        }

        if not files:
            logger.info("No files in %s — nothing to process.", self.settings.incoming_prefix)
            return summary

        logger.info("Processing batch of %s file(s) from %s", len(files), self.settings.incoming_prefix)
        for s3_key in files:
            try:
                self.process_file(s3_key)
                summary["processed"] += 1
            except ValidationFailedError as exc:
                summary["failed"] += 1
                summary["errors"].append(
                    {
                        "file": s3_key,
                        "stage": exc.stage,
                        "checks": exc.failed_checks,
                        "details": exc.details,
                    }
                )
                self._safe_move_to_failed(s3_key)
            except Exception as exc:
                summary["failed"] += 1
                summary["errors"].append(
                    {
                        "file": s3_key,
                        "stage": "unexpected",
                        "checks": [str(exc)],
                        "details": {},
                    }
                )
                logger.exception("Unexpected error while processing %s", s3_key)
                self._safe_move_to_failed(s3_key)

        logger.info(
            "Batch finished: processed=%s failed=%s total=%s",
            summary["processed"],
            summary["failed"],
            summary["total_files"],
        )

        if summary["failed"] > 0:
            # One email per DAG run (all files currently in incoming/).
            self._send_batch_failure_email(summary)

        return summary

    def process_file(self, s3_key: str) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_json = os.path.join(tmp_dir, "source.json")
            self.minio.download_file(s3_key, local_json)

            with open(local_json, encoding="utf-8") as handle:
                payload = json.load(handle)

            records = self._normalize_json_payload(payload)
            event_date = self._extract_event_date(records, s3_key)

            self._run_soda_checks(records, tmp_dir)
            ge_result = self._run_ge_checks(records)
            doc_id = self._build_doc_id(s3_key)
            self._publish_data_docs(doc_id, ge_result)
            self._move_to_processed(s3_key, event_date)

    def _move_to_failed(self, s3_key: str) -> None:
        dest_key = f"{self.settings.failed_prefix.rstrip('/')}/{Path(s3_key).name}"
        self.minio.move_object(s3_key, dest_key)
        logger.warning("File %s moved to %s", s3_key, dest_key)

    def _safe_move_to_failed(self, s3_key: str) -> None:
        try:
            self._move_to_failed(s3_key)
        except Exception:
            logger.exception(
                "Failed to move %s into %s after a processing failure; "
                "it will be retried on the next DAG run.",
                s3_key, self.settings.failed_prefix,
            )

    def _send_batch_failure_email(self, summary: Dict[str, Any]) -> None:
        body = EmailNotifier.format_batch_failure_email(summary)
        self.email.send_alert(
            subject=(
                f"[Data Quality] Batch failed: "
                f"{summary['failed']}/{summary['total_files']} files"
            ),
            body=body,
        )

    @staticmethod
    def _normalize_json_payload(raw_data: Any) -> List[Dict[str, Any]]:
        if isinstance(raw_data, list):
            return raw_data
        if isinstance(raw_data, dict):
            return [raw_data]
        raise ValueError(f"Unsupported JSON payload type: {type(raw_data).__name__}")

    @staticmethod
    def _extract_event_date(records: List[Dict[str, Any]], s3_key: str) -> str:
        for record in records:
            event_time = record.get("event_time")
            if isinstance(event_time, str):
                match = EVENT_TIME_PATTERN.match(event_time)
                if match:
                    return match.group(1)
        logger.warning("Could not parse event_time for %s, using processing date", s3_key)
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _load_soda_checks(self, table_name: str) -> str:
        if os.path.exists(self.settings.soda_checks_path):
            with open(self.settings.soda_checks_path, encoding="utf-8") as handle:
                checks_yaml = handle.read()
            return checks_yaml.replace(f"checks for {DEFAULT_SODA_TABLE}:", f"checks for {table_name}:")

        return f"""checks for {table_name}:
  - row_count > 0
  - missing_count(transaction_id) = 0
  - missing_count(user_id) = 0
  - missing_count(payment_method) = 0
  - missing_count(event_time) = 0
  - missing_count(status) = 0
"""

    @staticmethod
    def _extract_soda_error_messages(scan: Scan) -> List[str]:
        messages: List[str] = []
        for entry in scan.get_scan_results().get("logs", []):
            level = entry.get("level")
            message = entry.get("message", "")
            if level not in {"ERROR", "WARNING"}:
                continue
            if message.startswith("Soda Core"):
                continue
            if message.startswith("Scan summary"):
                continue
            messages.append(message)
        return messages

    def _run_soda_checks(self, records: List[Dict[str, Any]], tmp_dir: str) -> None:
        # Unique table name per file — DuckDB rejects reusing the same name in one process.
        table_name = f"scan_{uuid.uuid4().hex[:12]}"
        json_path = os.path.join(tmp_dir, f"{table_name}.json")
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(records, handle)

        config = f"""data_source transactions_ds:
  type: duckdb
  path: {json_path}
"""
        scan = Scan()
        scan.add_configuration_yaml_str(config)
        scan.set_data_source_name("transactions_ds")
        scan.add_sodacl_yaml_str(self._load_soda_checks(table_name))
        scan.execute()

        if scan.has_error_logs():
            error_messages = self._extract_soda_error_messages(scan)
            raise ValidationFailedError(
                stage="soda",
                failed_checks=error_messages or ["soda_scan_error"],
                details={"hint": "Soda scan failed before checks could run"},
            )

        failed_checks = [
            check.get("name", "unknown_check")
            for check in scan.get_scan_results().get("checks", [])
            if check.get("outcome") == "fail"
        ]
        if failed_checks:
            raise ValidationFailedError(stage="soda", failed_checks=failed_checks)

    def _build_expectation_suite(self) -> ExpectationSuite:
        return ExpectationSuite(
            name="transaction_checks",
            expectations=[
                ExpectColumnValuesToBeUnique(column="transaction_id"),
                ExpectColumnValuesToNotBeNull(column="transaction_id"),
                ExpectColumnValuesToNotBeNull(column="user_id"),
                ExpectColumnValuesToMatchStrftimeFormat(
                    column="event_time",
                    strftime_format="%Y-%m-%dT%H:%M:%SZ",
                ),
                ExpectColumnValuesToBeBetween(column="amount", min_value=0, max_value=10000),
                ExpectColumnValuesToBeInSet(column="currency", value_set=["USD", "EUR"]),
                ExpectColumnValuesToNotBeNull(column="payment_method"),
                ExpectColumnValuesToBeInSet(
                    column="payment_method",
                    value_set=["credit_card", "paypal", "apple_pay"],
                ),
                ExpectColumnValuesToBeInSet(
                    column="status",
                    value_set=["completed", "pending", "failed"],
                ),
                ExpectColumnValuesToBeBetween(column="quantity", min_value=1, max_value=1000),
                ExpectColumnValuesToBeBetween(
                    column="discount_percent",
                    min_value=0,
                    max_value=100,
                ),
                ExpectColumnPairValuesAToBeGreaterThanB(
                    column_A="amount",
                    column_B="discount_percent",
                    or_equal=False,
                ),
            ],
        )

    def _run_ge_checks(self, records: List[Dict[str, Any]]):
        gx.get_context(mode="ephemeral")
        dataframe = pd.DataFrame(records)
        suite = self._build_expectation_suite()
        validator = build_pandas_validator_with_data(dataframe)
        validator.expectation_suite = suite
        result = validator.validate()

        if not result.success:
            failed_checks = [
                item.expectation_config.type
                for item in result.results
                if not item.success
            ]
            raise ValidationFailedError(stage="great_expectations", failed_checks=failed_checks)

        return result

    def _build_doc_id(self, s3_key: str) -> str:
        stem = Path(s3_key).stem
        return stem.replace("/", "_")

    def _publish_data_docs(self, doc_id: str, validation_result) -> None:
        renderer = ValidationResultsPageRenderer()
        rendered = renderer.render(validation_result)
        html = DefaultJinjaPageView().render(rendered)

        object_key = f"{self.settings.data_docs_prefix.rstrip('/')}/{doc_id}/index.html"
        self.minio.put_object(
            key=object_key,
            body=html.encode("utf-8"),
            content_type="text/html",
        )

    def _move_to_processed(self, s3_key: str, event_date: str) -> None:
        dest_key = (
            f"{self.settings.processed_prefix.rstrip('/')}/"
            f"date={event_date}/{Path(s3_key).name}"
        )
        self.minio.move_object(s3_key, dest_key)
        logger.info("File %s moved to %s", s3_key, dest_key)


def build_processor() -> BatchProcessor:
    settings = AppSettings.from_env()
    minio = MinIOClient(
        endpoint=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
    )
    return BatchProcessor(settings=settings, minio_client=minio, email_notifier=EmailNotifier.from_env())

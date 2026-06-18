import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    incoming_prefix: str
    failed_prefix: str
    processed_prefix: str
    data_docs_prefix: str
    soda_checks_path: str

    @classmethod
    def from_env(cls) -> "AppSettings":
        return cls(
            s3_endpoint=os.getenv("S3_ENDPOINT", "http://minio:9000"),
            s3_access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
            s3_secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
            s3_bucket=os.getenv("S3_BUCKET", "data-quality"),
            incoming_prefix=os.getenv("INCOMING_PREFIX", "incoming"),
            failed_prefix=os.getenv("FAILED_PREFIX", "failed"),
            processed_prefix=os.getenv("PROCESSED_PREFIX", "processed"),
            data_docs_prefix=os.getenv("DATA_DOCS_PREFIX", "data_docs"),
            soda_checks_path=os.getenv("SODA_CHECKS_PATH", "/opt/airflow/soda/checks.yml"),
        )

    def minio_conn(self) -> dict[str, str]:
        return {
            "endpoint": self.s3_endpoint,
            "access_key": self.s3_access_key,
            "secret_key": self.s3_secret_key,
        }

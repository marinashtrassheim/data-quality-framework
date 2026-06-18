import logging
import json
import tempfile
from typing import List, Dict, Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class MinIOClient:
    """Thin wrapper around boto3 S3 API for MinIO."""
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version='s3v4'),
            use_ssl=secure,
        )

    def ensure_bucket_exists(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
            logger.info(f"Bucket {self.bucket} created")

    def list_objects(self, prefix: str = "") -> List[str]:
        objects = []
        try:
            paginator = self.client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                if 'Contents' in page:
                    objects.extend(obj['Key'] for obj in page['Contents'])
        except ClientError as e:
            logger.error(f"Failed to list objects: {e}")
            raise
        return objects

    def download_file(self, key: str, local_path: str) -> None:
        self.client.download_file(self.bucket, key, local_path)

    def upload_file(self, local_path: str, key: str) -> None:
        self.client.upload_file(local_path, self.bucket, key)

    def put_object(self, key: str, body: bytes, content_type: str = "application/json") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    def move_object(self, source_key: str, dest_key: str) -> None:
        copy_source = {'Bucket': self.bucket, 'Key': source_key}
        self.client.copy_object(Bucket=self.bucket, CopySource=copy_source, Key=dest_key)
        self.client.delete_object(Bucket=self.bucket, Key=source_key)

    def delete_object(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def read_json(self, key: str) -> Dict[str, Any]:
        with tempfile.NamedTemporaryFile(mode='r', suffix='.json') as tmp:
            self.download_file(key, tmp.name)
            tmp.seek(0)
            return json.load(tmp)
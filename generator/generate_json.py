import json
import logging
import os
import random
import time
import uuid
from datetime import datetime

from botocore.exceptions import ClientError
from common.minio_client import MinIOClient

logging.basicConfig(
    level=os.getenv("LOGLEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [generate_json] %(message)s",
)
logger = logging.getLogger(__name__)

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "data-quality")
INCOMING_PREFIX = os.getenv("INCOMING_PREFIX", "incoming")
FILES_PER_BATCH = int(os.getenv("FILES_PER_BATCH", "50"))
GENERATOR_INVALID_RATIO = float(os.getenv("GENERATOR_INVALID_RATIO", "0.3"))
DURATION_SEC = int(os.getenv("DURATION_SEC", "120"))
BATCH_INTERVAL = int(os.getenv("BATCH_INTERVAL", "30"))

CURRENCY = ["USD", "EUR"]
STATUS = ["completed", "pending", "failed"]
PAYMENT_METHODS = ["credit_card", "paypal", "apple_pay"]


def random_datetime():
    year = 2025
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    hour = random.randint(0, 23)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return datetime(year, month, day, hour, minute, second).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def build_event():
    is_invalid = random.random() < GENERATOR_INVALID_RATIO

    transaction_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    event_time = random_datetime()
    amount = random.randint(1, 10000)
    currency = random.choice(CURRENCY)
    payment_method = random.choice(PAYMENT_METHODS)
    status = random.choice(STATUS)
    quantity = random.randint(1, 100)
    discount_percent = random.randint(1, 50)

    if is_invalid:
        # Pick one field to corrupt — different checks may catch it in Soda or GE.
        error_type = random.choice([
            "transaction_id",
            "user_id",
            "event_time",
            "amount",
            "currency",
            "payment_method",
            "status",
            "quantity",
            "discount_percent",
        ])
        if error_type == "transaction_id":
            transaction_id = None
        elif error_type == "user_id":
            user_id = None
        elif error_type == "event_time":
            event_time = "invalid_date_string"
        elif error_type == "amount":
            amount = random.randint(10001, 10100)
        elif error_type == "currency":
            currency = random.choice(["GPG", "IGT", "JPY"])
        elif error_type == "payment_method":
            payment_method = random.choice(["cash", "debit_card", "no_payment"])
        elif error_type == "status":
            status = None
        elif error_type == "quantity":
            quantity = random.randint(1001, 2000)
        elif error_type == "discount_percent":
            discount_percent = random.randint(-100, -1)
    return {
        "transaction_id": transaction_id,
        "user_id": user_id,
        "event_time": event_time,
        "amount": amount,
        "currency": currency,
        "payment_method": payment_method,
        "status": status,
        "quantity": quantity,
        "discount_percent": discount_percent,
    }


def upload_events():
    client = MinIOClient(
        endpoint=S3_ENDPOINT,
        access_key=S3_ACCESS_KEY,
        secret_key=S3_SECRET_KEY,
        bucket=S3_BUCKET
    )

    for attempt in range(10):
        try:
            client.ensure_bucket_exists()
            break
        except ClientError:
            if attempt == 9:
                raise
            logger.warning("MinIO not ready, retrying in 3s...")
            time.sleep(3)

    start_time = time.time()
    end_time = start_time + DURATION_SEC
    batch_count = 0

    while time.time() < end_time:
        batch_start = time.time()
        logger.info(f"Starting batch {batch_count + 1} at {datetime.now().isoformat()}")
        now = datetime.now()
        partition = f"{INCOMING_PREFIX}/{now.strftime('%Y-%m-%d')}/{now.strftime('%H%M%S')}"
        s3_prefix = f"{partition}/"

        events = [build_event() for _ in range(FILES_PER_BATCH)]

        uploaded = 0
        for idx, event in enumerate(events):
            file_name = f"{now.strftime('%Y%m%d_%H%M%S')}_{idx:04d}_{uuid.uuid4().hex[:8]}.json"
            s3_key = s3_prefix + file_name
            body = json.dumps(event, indent=2).encode('utf-8')
            try:
                client.put_object(key=s3_key, body=body, content_type="application/json")
                uploaded += 1
            except ClientError as e:
                logger.error(f"Failed to upload {s3_key}: {e}")

        logger.info(f"Batch {batch_count + 1}: uploaded {uploaded} files to s3://{S3_BUCKET}/{s3_prefix}")

        batch_count += 1

        elapsed = time.time() - batch_start
        wait_time = max(0.0, BATCH_INTERVAL - elapsed)
        if wait_time > 0 and (time.time() + wait_time) < end_time:
            logger.info(f"Waiting {wait_time:.1f} seconds until next batch...")
            time.sleep(wait_time)
        elif time.time() + wait_time >= end_time:
            break

    logger.info(f"Generation finished. Total batches: {batch_count}")


if __name__ == "__main__":
    upload_events()

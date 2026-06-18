FROM apache/airflow:2.8.1-python3.11

USER airflow

RUN pip install --no-cache-dir \
    great-expectations==1.18.1 \
    soda-core==3.5.6 \
    soda-core-duckdb==3.5.6 \
    "duckdb>=1.0,<2.0" \
    "boto3>=1.34,<2.0"

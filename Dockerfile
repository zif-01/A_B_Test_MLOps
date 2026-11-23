FROM apache/airflow:2.10.5-python3.11

WORKDIR /opt/airflow/project
COPY --chown=airflow:root pyproject.toml README.md ./
COPY --chown=airflow:root src ./src
USER airflow
RUN pip install --no-cache-dir .

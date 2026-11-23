# Reproducible A/B-test analysis pipeline

This project turns the analysis from
[A_B_Test_showcase](https://github.com/zif-01/A_B_Test_showcase) into a
reproducible pipeline. It automates experiment-data checks, SRM detection,
metric and statistical analysis, subgroup analysis, reporting, and a local
file-based alert. It does **not** retrain a model: an ordinary A/B test has no
model to retrain.

The MVP uses synthetic data, Python, DVC with a local remote, and a Dockerized
Airflow instance. The analysis can also run directly from the CLI without
Airflow.

## Requirements

- Docker and Docker Compose
- Python 3.11+ and [uv](https://docs.astral.sh/uv/) for local development
- DVC for data versioning (`uv run dvc ...`)

## Run from scratch

```bash
uv sync --extra dev
```

The local DVC remote is preconfigured in `.dvc/config` as `../.dvc-storage`,
outside the Git repository. Reproduce the workflow and optionally push its
cached data and reports to that local remote:

```bash
uv run dvc repro
uv run dvc push
```

For a direct CLI run without DVC, generate and analyze the data explicitly:

```bash
uv run ab-test generate --config configs/default.yaml --output data/raw/experiment.csv
uv run ab-test run --config configs/default.yaml --input data/raw/experiment.csv --output-dir artifacts/current
```

The analysis command writes `analysis.json`, `report.md`, `manifest.json`, and
`alert.txt` under `artifacts/current`. A non-zero exit code means that a data
quality or SRM gate failed; the diagnostic artifacts are still written.

The default DVC remote is local. For a shared team setup, configure an
S3-compatible remote using DVC's standard remote configuration. Keep any
credentials outside Git.

## Airflow in Docker

Generate the input file first, then start Airflow:

```bash
uv run ab-test generate --config configs/default.yaml --output data/raw/experiment.csv
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080). Airflow Standalone creates
a local admin account and prints the credentials in its container logs:

```bash
docker compose logs airflow
```

Trigger the `ab_test_analysis` DAG manually. The default experiment config and
CSV are mounted into the container. A DAG run can override `experiment_id` or
`input_path` with its JSON configuration, for example:

```json
{
  "experiment_id": "checkout_november",
  "input_path": "/opt/airflow/project/data/raw/experiment.csv"
}
```

The DAG writes a run-specific folder under `artifacts/airflow/`. A producer
that detects a new file can trigger the Airflow DAG through its API and pass
that file's mounted path as `input_path`. To enable periodic runs, set
`AB_TEST_SCHEDULE` in the shell or an ignored `.env` file to a cron expression
(for example, `0 8 * * *`) and ensure the input file is refreshed before each
scheduled run.
For unattended deployments, configure Airflow authentication and networking
before exposing its webserver.

Expected data-quality or SRM anomalies produce a report and alert before the
DAG is marked failed. Unexpected task failures are reported by the final alert
task when Airflow can still execute it.

## Data contract and analysis

Each row represents one randomized unit. Required columns:

- `user_id`: unique, non-empty assignment unit
- `variant`: configured control or treatment group
- configured metric columns: numeric and non-null
- configured subgroup columns: non-null categorical values

The default configuration includes a binary conversion primary metric and a
continuous revenue guardrail. Binary metrics use a two-proportion z-test and
an unpooled normal confidence interval; continuous metrics use Welch's t-test
and a Welch confidence interval. Subgroup p-values are adjusted with the
configured Holm procedure.

The pipeline checks the sample ratio before inferential analysis. If SRM fails,
it records the group counts and p-value and does not present treatment tests as
reliable. MDE is reported as an approximate detectable absolute difference for
the observed control rate and sample size. Power at the configured planned MDE
is also reported as a planning diagnostic, not as evidence that a null result
means no effect.

## Tests and development

```bash
uv run pytest
uv run ab-test generate --config configs/default.yaml --output data/raw/experiment.csv
uv run ab-test run --config configs/default.yaml --input data/raw/experiment.csv --output-dir artifacts/current
```

The test suite covers validation, SRM gating, metric calculations, subgroup
adjustment, and repeatability of the synthetic generator. The report manifest
records the input and config SHA-256 hashes, seed, package version, Git commit
when available, and whether the Git worktree was dirty. DVC records dataset
and pipeline-output hashes in its lockfile; commit that lockfile alongside the
code. Compare metric definitions and inputs with the notebook in
`A_B_Test_showcase` before interpreting a numeric comparison; this MVP does
not bundle or assume access to that repository's data.

An example report, analysis result, manifest, and alert generated from the
synthetic dataset are included under `examples/demo/`.

The DVC-managed CLI workflow versions its input and canonical outputs through
`dvc.lock`. Airflow keeps each run's outputs in a separate local folder and
records input/config hashes in its manifest; the local DVC remote can be used
to archive those folders as a follow-up operational step.

## Scope and next steps

- No model retraining is part of the A/B-analysis path.
- No Kaggle dataset or API key is needed. If a downloader is added later, keep
  the token in an environment variable or an ignored local config and never
  commit downloaded data or credentials.
- PySpark is intentionally not used for the demo-sized data. Consider it if
  data volume or compute time outgrows a single-machine pandas workflow.
- Final metric selection and business recommendations remain human decisions.

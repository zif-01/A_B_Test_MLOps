from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml
from airflow import DAG
from airflow.exceptions import AirflowFailException
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from ab_test_pipeline.analysis import (
    analyze_after_checks,
    check_srm,
    validate_data,
)
from ab_test_pipeline.reporting import (
    build_manifest,
    render_report,
    write_alert,
    write_json,
)

PROJECT = Path("/opt/airflow/project")
DEFAULT_CONFIG = PROJECT / "configs/default.yaml"


def _context_settings(context):
    conf = (context.get("dag_run") and context["dag_run"].conf) or {}
    with DEFAULT_CONFIG.open(encoding="utf-8") as source:
        config = yaml.safe_load(source)
    experiment_id = str(conf.get("experiment_id", config["experiment_id"]))
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", experiment_id)
    run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", context["run_id"])
    run_dir = PROJECT / "artifacts" / "airflow" / safe_id / run_id
    input_path = Path(conf.get("input_path", PROJECT / "data/raw/experiment.csv"))
    return config, experiment_id, input_path, run_dir


def pull_data(**context):
    _, _, input_path, run_dir = _context_settings(context)
    if not input_path.is_file():
        raise FileNotFoundError(f"Experiment input file not found: {input_path}")
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "input.csv"
    shutil.copyfile(input_path, target)
    return str(target)


def validate_task(**context):
    config, _, _, run_dir = _context_settings(context)
    input_path = Path(context["ti"].xcom_pull(task_ids="pull_data"))
    validation = validate_data(pd.read_csv(input_path), config)
    write_json(run_dir / "validation.json", validation)
    return validation


def srm_task(**context):
    config, _, _, run_dir = _context_settings(context)
    validation = context["ti"].xcom_pull(task_ids="validate_data")
    if not validation or not validation["passed"]:
        srm = {"passed": False, "p_value": None, "reason": "validation failed"}
    else:
        input_path = Path(context["ti"].xcom_pull(task_ids="pull_data"))
        srm = check_srm(pd.read_csv(input_path), config)
    write_json(run_dir / "srm.json", srm)
    return srm


def analyze_task(**context):
    config, _, _, run_dir = _context_settings(context)
    input_path = Path(context["ti"].xcom_pull(task_ids="pull_data"))
    validation = context["ti"].xcom_pull(task_ids="validate_data")
    srm = context["ti"].xcom_pull(task_ids="check_srm")
    result = analyze_after_checks(pd.read_csv(input_path), config, validation, srm)
    write_json(run_dir / "analysis.json", result)
    return result["status"]


def report_task(**context):
    config, experiment_id, _, run_dir = _context_settings(context)
    input_path = Path(context["ti"].xcom_pull(task_ids="pull_data"))
    result_path = run_dir / "analysis.json"
    if not result_path.is_file():
        result = {
            "status": "failed",
            "reason": "Analysis task did not produce results",
            "validation": {"passed": False, "errors": ["Analysis task failed"], "rows": 0},
            "srm": {"passed": False, "p_value": None, "observed": {}},
            "metrics": [],
            "subgroups": [],
            "precision": None,
        }
        write_json(result_path, result)
    else:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = build_manifest(
        DEFAULT_CONFIG,
        input_path,
        experiment_id,
        int(config.get("seed", 41)),
    )
    write_json(run_dir / "manifest.json", manifest)
    (run_dir / "report.md").write_text(render_report(result, manifest), encoding="utf-8")
    return result["status"]


def notify_task(**context):
    _, experiment_id, _, run_dir = _context_settings(context)
    result_path = run_dir / "analysis.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {"status": "failed", "reason": "A pipeline task failed before analysis"}
    write_alert(run_dir / "alert.txt", result, experiment_id)
    if result["status"] != "completed":
        raise AirflowFailException(
            f"A/B analysis finished with status {result['status']}; see {run_dir}"
        )


with DAG(
    dag_id="ab_test_analysis",
    description="Reproducible experiment checks, analysis, report, and alert",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    schedule=os.getenv("AB_TEST_SCHEDULE") or None,
    catchup=False,
    default_args={"owner": "data-science", "retries": 1, "retry_delay": timedelta(minutes=2)},
    tags=["ab-test", "dvc", "portfolio"],
) as dag:
    load = PythonOperator(task_id="pull_data", python_callable=pull_data)
    validate = PythonOperator(task_id="validate_data", python_callable=validate_task)
    srm = PythonOperator(task_id="check_srm", python_callable=srm_task)
    analyze = PythonOperator(task_id="analyze", python_callable=analyze_task)
    report = PythonOperator(task_id="build_report", python_callable=report_task)
    notify = PythonOperator(
        task_id="send_alert",
        python_callable=notify_task,
        trigger_rule=TriggerRule.ALL_DONE,
    )
    load >> validate >> srm >> analyze >> report >> notify

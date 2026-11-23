import json
from pathlib import Path

import pandas as pd
import yaml

from ab_test_pipeline.cli import run_pipeline
from ab_test_pipeline.data import write_synthetic_data

ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_writes_reproducibility_artifacts(tmp_path):
    config_path = ROOT / "configs/default.yaml"
    input_path = write_synthetic_data(
        yaml.safe_load(config_path.read_text(encoding="utf-8")),
        tmp_path / "input.csv",
        seed=41,
    )
    output = tmp_path / "artifacts"
    result = run_pipeline(config_path, input_path, output, seed=41)
    repeat_result = run_pipeline(
        config_path, input_path, tmp_path / "repeat", seed=41
    )

    assert result["status"] == "completed"
    assert result == repeat_result
    assert {"analysis.json", "manifest.json", "report.md", "alert.txt"} <= {
        path.name for path in output.iterdir()
    }
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["package_version"]
    assert manifest["input_sha256"]
    assert manifest["config_sha256"]
    assert "## Metrics" in (output / "report.md").read_text(encoding="utf-8")
    assert "status=completed" in (output / "alert.txt").read_text(encoding="utf-8")


def test_pipeline_keeps_diagnostics_for_srm_failure(tmp_path):
    config_path = ROOT / "configs/default.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = pd.DataFrame(
        {
            "user_id": [f"u{i}" for i in range(20)],
            "variant": ["control"] * 18 + ["treatment"] * 2,
            "converted": [0, 1] * 10,
            "revenue": [1.0] * 20,
            "country": ["US"] * 20,
        }
    )
    input_path = tmp_path / "srm.csv"
    data.to_csv(input_path, index=False)
    output = tmp_path / "artifacts"

    result = run_pipeline(config_path, input_path, output)

    assert result["status"] == "srm_failed"
    assert (output / "report.md").is_file()
    assert "status=srm_failed" in (output / "alert.txt").read_text(encoding="utf-8")

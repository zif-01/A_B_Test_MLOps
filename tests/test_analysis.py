from pathlib import Path

import pandas as pd
import yaml

from ab_test_pipeline.analysis import (
    adjust_p_values,
    analyze_experiment,
    check_srm,
    compare_metric,
    validate_data,
)
from ab_test_pipeline.data import generate_synthetic_data

ROOT = Path(__file__).resolve().parents[1]


def load_config():
    with (ROOT / "configs/default.yaml").open(encoding="utf-8") as source:
        return yaml.safe_load(source)


def test_synthetic_data_is_reproducible():
    config = load_config()
    first = generate_synthetic_data(config, seed=7)
    second = generate_synthetic_data(config, seed=7)
    pd.testing.assert_frame_equal(first, second)


def test_validation_detects_duplicate_users():
    config = load_config()
    data = generate_synthetic_data(config, seed=7)
    data.loc[1, "user_id"] = data.loc[0, "user_id"]
    result = validate_data(data, config)
    assert not result["passed"]
    assert "user_id contains duplicates" in result["errors"]


def test_srm_gate_prevents_inferential_results():
    config = load_config()
    data = generate_synthetic_data(config, seed=7)
    treatment_rows = data.index[data["variant"] == "treatment"]
    data.loc[treatment_rows[:-100], "variant"] = "control"
    result = analyze_experiment(data, config)
    assert result["status"] == "srm_failed"
    assert result["metrics"] == []


def test_balanced_data_produces_metrics_subgroups_and_precision():
    config = load_config()
    data = generate_synthetic_data(config, seed=41)
    result = analyze_experiment(data, config)
    assert result["status"] == "completed"
    assert {metric["name"] for metric in result["metrics"]} == {
        "conversion",
        "revenue",
    }
    assert result["subgroups"]
    assert 0 <= result["precision"]["power_at_planned_mde"] <= 1


def test_holm_adjustment_is_monotonic_in_sorted_order():
    adjusted = adjust_p_values([0.04, 0.01, 0.03], method="holm")
    assert adjusted == [0.06, 0.03, 0.06]


def test_srm_counts_match_expected_split():
    config = load_config()
    data = generate_synthetic_data(config, seed=11)
    result = check_srm(data, config)
    assert result["passed"]
    assert result["observed"] == {"control": 1200, "treatment": 1200}


def test_metric_comparisons_return_expected_effects_and_tests():
    binary = compare_metric(
        pd.Series([0, 0, 1, 1]),
        pd.Series([1, 1, 1, 0]),
        metric_type="binary",
        alpha=0.05,
    )
    continuous = compare_metric(
        pd.Series([1, 2, 3, 4]),
        pd.Series([3, 4, 5, 6]),
        metric_type="continuous",
        alpha=0.05,
    )

    assert binary["mean_control"] == 0.5
    assert binary["mean_treatment"] == 0.75
    assert binary["difference"] == 0.25
    assert binary["test"] == "two_proportion_z_test"
    assert continuous["difference"] == 2.0
    assert continuous["test"] == "welch_t_test"

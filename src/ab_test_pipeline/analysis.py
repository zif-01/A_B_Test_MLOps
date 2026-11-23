from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from scipy import stats


def validate_data(data: pd.DataFrame, config: dict) -> dict:
    expected_variants = set(config["allocation"])
    metric_specs = config["metrics"]
    subgroup_columns = config.get("subgroups", [])
    required = {"user_id", "variant"}
    required.update(metric["column"] for metric in metric_specs)
    required.update(subgroup_columns)
    errors: list[str] = []

    missing_columns = sorted(required.difference(data.columns))
    if missing_columns:
        errors.append(f"Missing columns: {', '.join(missing_columns)}")
        return {"passed": False, "errors": errors, "rows": int(len(data))}

    if len(expected_variants) != 2:
        errors.append("This pipeline supports exactly two experiment variants")
    allocation_values = np.asarray(
        [float(value) for value in config["allocation"].values()], dtype=float
    )
    if not np.isfinite(allocation_values).all() or np.any(allocation_values <= 0):
        errors.append("Allocation proportions must be finite and greater than 0")
    for parameter in ("alpha", "srm_alpha"):
        value = float(config.get(parameter, 0.05 if parameter == "alpha" else 0.001))
        if not 0 < value < 1:
            errors.append(f"{parameter} must be between 0 and 1")
    if not 0 < float(config.get("target_power", 0.8)) < 1:
        errors.append("target_power must be between 0 and 1")
    if not 0 <= float(config.get("planned_mde", 0.0)) <= 1:
        errors.append("planned_mde must be between 0 and 1")

    if data.empty:
        errors.append("Dataset is empty")
    if data["user_id"].isna().any() or data["user_id"].astype(str).str.strip().eq("").any():
        errors.append("user_id contains missing or empty values")
    if data["user_id"].duplicated().any():
        errors.append("user_id contains duplicates")
    if data["variant"].isna().any():
        errors.append("variant contains missing values")
    observed_variants = set(data["variant"].dropna().unique())
    if observed_variants != expected_variants:
        errors.append(
            f"Expected variants {sorted(expected_variants)}, got {sorted(observed_variants)}"
        )
    group_sizes = data["variant"].value_counts()
    for variant in expected_variants:
        if group_sizes.get(variant, 0) < 2:
            errors.append(f"Variant {variant} has fewer than 2 units")

    for metric in metric_specs:
        column = metric["column"]
        values = pd.to_numeric(data[column], errors="coerce")
        if values.isna().any():
            errors.append(f"{column} contains missing or non-numeric values")
            continue
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            errors.append(f"{column} contains non-finite values")
        if metric["type"] == "binary" and not values.isin([0, 1]).all():
            errors.append(f"{column} must contain only 0 and 1")
        if "min" in metric and (values < float(metric["min"])).any():
            errors.append(f"{column} contains values below {metric['min']}")
        if "max" in metric and (values > float(metric["max"])).any():
            errors.append(f"{column} contains values above {metric['max']}")

    for column in subgroup_columns:
        if data[column].isna().any():
            errors.append(f"{column} contains missing subgroup values")

    allocation_total = sum(float(value) for value in config["allocation"].values())
    if not np.isclose(allocation_total, 1.0):
        errors.append("Configured allocation proportions must sum to 1")

    return {"passed": not errors, "errors": errors, "rows": int(len(data))}


def check_srm(data: pd.DataFrame, config: dict) -> dict:
    variants = list(config["allocation"])
    if len(variants) != 2:
        raise ValueError("SRM check supports exactly two experiment variants")
    observed = data["variant"].value_counts().reindex(variants, fill_value=0)
    total = int(observed.sum())
    proportions = np.array([float(config["allocation"][key]) for key in variants])
    expected = proportions * total
    if total == 0 or np.any(expected == 0):
        return {
            "passed": False,
            "statistic": None,
            "p_value": 0.0,
            "observed": {key: int(observed[key]) for key in variants},
            "expected": {key: float(value) for key, value in zip(variants, expected)},
            "alpha": float(config.get("srm_alpha", 0.001)),
        }
    statistic, p_value = stats.chisquare(observed.to_numpy(), f_exp=expected)
    alpha = float(config.get("srm_alpha", 0.001))
    return {
        "passed": bool(p_value >= alpha),
        "statistic": float(statistic),
        "p_value": float(p_value),
        "observed": {key: int(observed[key]) for key in variants},
        "expected": {key: float(value) for key, value in zip(variants, expected)},
        "alpha": alpha,
    }


def compare_metric(
    control: pd.Series,
    treatment: pd.Series,
    metric_type: str,
    alpha: float,
) -> dict:
    control = control.astype(float)
    treatment = treatment.astype(float)
    n_control, n_treatment = len(control), len(treatment)
    mean_control, mean_treatment = float(control.mean()), float(treatment.mean())
    difference = mean_treatment - mean_control

    if metric_type == "binary":
        successes_control = float(control.sum())
        successes_treatment = float(treatment.sum())
        pooled = (successes_control + successes_treatment) / (n_control + n_treatment)
        null_se = np.sqrt(
            pooled * (1 - pooled) * (1 / n_control + 1 / n_treatment)
        )
        z_statistic = 0.0 if null_se == 0 else difference / null_se
        p_value = float(2 * stats.norm.sf(abs(z_statistic)))
        ci_se = np.sqrt(
            mean_control * (1 - mean_control) / n_control
            + mean_treatment * (1 - mean_treatment) / n_treatment
        )
        critical = float(stats.norm.ppf(1 - alpha / 2))
        low, high = difference - critical * ci_se, difference + critical * ci_se
        test_name = "two_proportion_z_test"
    else:
        test = stats.ttest_ind(treatment, control, equal_var=False)
        var_control = float(control.var(ddof=1))
        var_treatment = float(treatment.var(ddof=1))
        se_squared = var_control / n_control + var_treatment / n_treatment
        if se_squared == 0:
            degrees_freedom = float(n_control + n_treatment - 2)
            low = high = difference
        else:
            degrees_freedom = se_squared**2 / (
                (var_control / n_control) ** 2 / (n_control - 1)
                + (var_treatment / n_treatment) ** 2 / (n_treatment - 1)
            )
            critical = float(stats.t.ppf(1 - alpha / 2, degrees_freedom))
            margin = critical * np.sqrt(se_squared)
            low, high = difference - margin, difference + margin
        p_value = float(test.pvalue) if np.isfinite(test.pvalue) else 1.0
        test_name = "welch_t_test"

    return {
        "n_control": int(n_control),
        "n_treatment": int(n_treatment),
        "mean_control": mean_control,
        "mean_treatment": mean_treatment,
        "difference": float(difference),
        "ci_low": float(low),
        "ci_high": float(high),
        "p_value": p_value,
        "significant": bool(p_value < alpha),
        "test": test_name,
    }


def adjust_p_values(values: Iterable[float], method: str = "holm") -> list[float]:
    p_values = np.asarray(list(values), dtype=float)
    if not len(p_values):
        return []
    if method not in {"holm", "bh"}:
        raise ValueError(f"Unsupported multiplicity method: {method}")
    order = np.argsort(p_values)
    sorted_values = p_values[order]
    m = len(p_values)
    if method == "holm":
        adjusted_sorted = np.maximum.accumulate(
            (m - np.arange(m)) * sorted_values
        )
    else:
        adjusted_sorted = sorted_values * m / (np.arange(m) + 1)
        adjusted_sorted = np.minimum.accumulate(adjusted_sorted[::-1])[::-1]
    adjusted = np.empty(m, dtype=float)
    adjusted[order] = np.minimum(adjusted_sorted, 1.0)
    return adjusted.tolist()


def _power_at_effect(
    baseline_rate: float, effect: float, sample_size: int, alpha: float
) -> float:
    treatment_rate = min(max(baseline_rate + effect, 0.0), 1.0)
    null_se = np.sqrt(
        2 * baseline_rate * (1 - baseline_rate) / sample_size
    )
    alternative_se = np.sqrt(
        baseline_rate * (1 - baseline_rate) / sample_size
        + treatment_rate * (1 - treatment_rate) / sample_size
    )
    if null_se == 0:
        return float(effect != 0)
    critical = float(stats.norm.ppf(1 - alpha / 2)) * null_se
    if alternative_se == 0:
        return float(abs(effect) >= critical)
    return float(
        stats.norm.cdf((-critical - effect) / alternative_se)
        + stats.norm.sf((critical - effect) / alternative_se)
    )


def calculate_precision(
    baseline_rate: float, sample_size: int, alpha: float, planned_mde: float, target_power: float
) -> dict:
    low, high = 0.0, 1.0
    for _ in range(60):
        middle = (low + high) / 2
        if _power_at_effect(baseline_rate, middle, sample_size, alpha) < target_power:
            low = middle
        else:
            high = middle
    return {
        "method": "normal_approximation_two_sided",
        "control_rate": float(baseline_rate),
        "n_per_group": int(sample_size),
        "estimated_mde": float(high),
        "planned_mde": float(planned_mde),
        "power_at_planned_mde": _power_at_effect(
            baseline_rate, float(planned_mde), sample_size, alpha
        ),
        "target_power": float(target_power),
    }


def analyze_after_checks(
    data: pd.DataFrame, config: dict, validation: dict, srm: dict
) -> dict:
    result = {"validation": validation, "srm": srm, "metrics": [], "subgroups": []}
    if not validation["passed"]:
        result.update(status="failed", reason="Data validation failed")
        return result
    if not srm["passed"]:
        result.update(status="srm_failed", reason="Sample ratio mismatch detected")
        return result

    control_name, treatment_name = list(config["allocation"])
    control = data.loc[data["variant"] == control_name]
    treatment = data.loc[data["variant"] == treatment_name]
    alpha = float(config.get("alpha", 0.05))
    for metric in config["metrics"]:
        comparison = compare_metric(
            control[metric["column"]],
            treatment[metric["column"]],
            metric["type"],
            alpha,
        )
        comparison.update(name=metric["name"], role=metric.get("role", "secondary"))
        result["metrics"].append(comparison)

    subgroup_rows = []
    for column in config.get("subgroups", []):
        for value, subset in data.groupby(column, observed=True, sort=True):
            subgroup_control = subset.loc[subset["variant"] == control_name]
            subgroup_treatment = subset.loc[subset["variant"] == treatment_name]
            if min(len(subgroup_control), len(subgroup_treatment)) < 2:
                continue
            for metric in config["metrics"]:
                comparison = compare_metric(
                    subgroup_control[metric["column"]],
                    subgroup_treatment[metric["column"]],
                    metric["type"],
                    alpha,
                )
                subgroup_rows.append(
                    {
                        "subgroup": column,
                        "value": str(value),
                        "metric": metric["name"],
                        **comparison,
                    }
                )
    method = config.get("multiplicity_method", "holm")
    for metric_name in {row["metric"] for row in subgroup_rows}:
        indexes = [
            index
            for index, row in enumerate(subgroup_rows)
            if row["metric"] == metric_name
        ]
        adjusted = adjust_p_values(
            [subgroup_rows[index]["p_value"] for index in indexes], method
        )
        for index, adjusted_p in zip(indexes, adjusted):
            subgroup_rows[index]["p_adjusted"] = adjusted_p
            subgroup_rows[index]["significant_adjusted"] = adjusted_p < alpha
    result["subgroups"] = subgroup_rows

    primary = next(
        (metric for metric in config["metrics"] if metric.get("role") == "primary"),
        None,
    )
    if primary and primary["type"] == "binary":
        primary_result = next(
            metric for metric in result["metrics"] if metric["name"] == primary["name"]
        )
        result["precision"] = calculate_precision(
            primary_result["mean_control"],
            primary_result["n_control"],
            alpha,
            float(config.get("planned_mde", 0.0)),
            float(config.get("target_power", 0.8)),
        )
    else:
        result["precision"] = None
    result.update(status="completed", reason=None)
    return result


def analyze_experiment(data: pd.DataFrame, config: dict) -> dict:
    validation = validate_data(data, config)
    srm = check_srm(data, config) if validation["passed"] else {
        "passed": False,
        "statistic": None,
        "p_value": None,
        "observed": {},
        "expected": {},
        "alpha": float(config.get("srm_alpha", 0.001)),
    }
    return analyze_after_checks(data, config, validation, srm)

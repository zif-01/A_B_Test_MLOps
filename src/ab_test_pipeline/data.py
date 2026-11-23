from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def generate_synthetic_data(config: dict, seed: int | None = None) -> pd.DataFrame:
    """Create a deterministic user-level experiment dataset."""
    settings = config["synthetic_data"]
    rng = np.random.default_rng(config.get("seed", 41) if seed is None else seed)
    n = int(settings["users_per_variant"])
    if n < 2:
        raise ValueError("users_per_variant must be at least 2")

    variants = np.repeat(["control", "treatment"], n)
    control_rate = float(settings["control_conversion_rate"])
    treatment_rate = control_rate + float(settings["treatment_conversion_lift"])
    if not 0 <= control_rate <= 1 or not 0 <= treatment_rate <= 1:
        raise ValueError("Synthetic conversion probabilities must be in [0, 1]")

    converted = np.concatenate(
        [
            rng.binomial(1, control_rate, n),
            rng.binomial(1, treatment_rate, n),
        ]
    )
    control_revenue = float(settings["control_mean_revenue"])
    treatment_revenue = control_revenue + float(
        settings["treatment_mean_revenue_lift"]
    )
    revenue = np.where(
        converted == 1,
        rng.gamma(shape=2.0, scale=np.where(variants == "control", control_revenue, treatment_revenue) / 2.0),
        0.0,
    )
    countries = rng.choice(["US", "GB", "CA"], size=2 * n, p=[0.6, 0.25, 0.15])
    order = rng.permutation(2 * n)
    return pd.DataFrame(
        {
            "user_id": np.asarray([f"user-{i:06d}" for i in range(2 * n)])[order],
            "variant": variants[order],
            "converted": converted[order].astype(int),
            "revenue": revenue[order].astype(float),
            "country": countries[order],
        }
    )


def write_synthetic_data(
    config: dict, output_path: str | Path, seed: int | None = None
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    generate_synthetic_data(config, seed).to_csv(path, index=False)
    return path

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from ab_test_pipeline.analysis import analyze_experiment
from ab_test_pipeline.data import write_synthetic_data
from ab_test_pipeline.reporting import (
    build_manifest,
    render_report,
    write_alert,
    write_json,
)


def load_config(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as source:
        config = yaml.safe_load(source)
    if not isinstance(config, dict):
        raise ValueError("Experiment config must be a YAML mapping")
    return config


def run_pipeline(
    config_path: str | Path,
    input_path: str | Path,
    output_dir: str | Path,
    seed: int | None = None,
    experiment_id: str | None = None,
) -> dict:
    config = load_config(config_path)
    effective_seed = int(config.get("seed", 41) if seed is None else seed)
    effective_experiment_id = experiment_id or config.get("experiment_id", "experiment")
    data = pd.read_csv(input_path)
    result = analyze_experiment(data, config)
    manifest = build_manifest(
        config_path, input_path, effective_experiment_id, effective_seed
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "analysis.json", result)
    write_json(output / "manifest.json", manifest)
    (output / "report.md").write_text(
        render_report(result, manifest), encoding="utf-8"
    )
    write_alert(output / "alert.txt", result, effective_experiment_id)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ab-test")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="generate synthetic experiment data")
    generate.add_argument("--config", required=True)
    generate.add_argument("--output", required=True)
    generate.add_argument("--seed", type=int)
    run = commands.add_parser("run", help="run the complete A/B analysis")
    run.add_argument("--config", required=True)
    run.add_argument("--input", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--seed", type=int)
    run.add_argument("--experiment-id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "generate":
            path = write_synthetic_data(
                load_config(args.config), args.output, args.seed
            )
            print(f"Wrote synthetic data to {path}")
            return 0

        result = run_pipeline(
            args.config,
            args.input,
            args.output_dir,
            args.seed,
            args.experiment_id,
        )
        print(
            json.dumps(
                {"status": result["status"], "output_dir": args.output_dir},
                sort_keys=True,
            )
        )
        return 0 if result["status"] == "completed" else 1
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as error:
        print(f"ab-test: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

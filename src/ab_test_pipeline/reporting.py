from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from ab_test_pipeline import __version__


def file_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(
    config_path: str | Path,
    input_path: str | Path,
    experiment_id: str,
    seed: int,
) -> dict:
    repository = Path(config_path).resolve().parent.parent
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
            cwd=repository,
        ).stdout.strip()
        git_worktree_dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
                cwd=repository,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        git_commit = None
        git_worktree_dirty = None
    return {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "package_version": __version__,
        "git_commit": git_commit,
        "git_worktree_dirty": git_worktree_dirty,
        "input_sha256": file_sha256(input_path),
        "config_sha256": file_sha256(config_path),
        "seed": int(seed),
    }


def render_report(result: dict, manifest: dict) -> str:
    lines = [
        f"# A/B test report: {manifest['experiment_id']}",
        "",
        f"- **Status:** `{result['status']}`",
        f"- **Generated (UTC):** {manifest['created_at_utc']}",
        f"- **Pipeline version:** `{manifest['package_version']}`",
        f"- **Input SHA-256:** `{manifest['input_sha256']}`",
        f"- **Config SHA-256:** `{manifest['config_sha256']}`",
        f"- **Git commit:** `{manifest['git_commit'] or 'unavailable'}`",
        f"- **Git worktree dirty:** `{manifest['git_worktree_dirty']}`",
        f"- **Seed:** `{manifest['seed']}`",
        "",
        "## Data checks",
        "",
        f"- Rows: {result['validation']['rows']}",
        f"- Validation: {'passed' if result['validation']['passed'] else 'failed'}",
    ]
    for error in result["validation"]["errors"]:
        lines.append(f"- Validation issue: {error}")
    srm = result["srm"]
    if srm.get("p_value") is not None:
        lines.extend(
            [
                f"- SRM: {'passed' if srm['passed'] else 'FAILED'} "
                f"(p={srm['p_value']:.6g}, alpha={srm['alpha']})",
                f"- Observed assignments: `{json.dumps(srm['observed'], sort_keys=True)}`",
            ]
        )
    else:
        lines.append("- SRM: not run because data validation failed")

    lines.extend(["", "## Metrics", ""])
    if result["metrics"]:
        lines.extend(
            [
                "| Metric | Role | Control | Treatment | Difference | 95% CI | p-value | Test |",
                "|---|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for metric in result["metrics"]:
            lines.append(
                f"| {metric['name']} | {metric['role']} | "
                f"{metric['mean_control']:.6g} | {metric['mean_treatment']:.6g} | "
                f"{metric['difference']:.6g} | [{metric['ci_low']:.6g}, "
                f"{metric['ci_high']:.6g}] | {metric['p_value']:.6g} | {metric['test']} |"
            )
    else:
        lines.append("Inferential metrics were not calculated.")

    lines.extend(["", "## Subgroups", ""])
    if result["subgroups"]:
        lines.extend(
            [
                "| Dimension | Value | Metric | Difference | p-value | Adjusted p-value |",
                "|---|---|---|---:|---:|---:|",
            ]
        )
        for row in result["subgroups"]:
            lines.append(
                f"| {row['subgroup']} | {row['value']} | {row['metric']} | "
                f"{row['difference']:.6g} | {row['p_value']:.6g} | "
                f"{row['p_adjusted']:.6g} |"
            )
    else:
        lines.append("No eligible subgroup comparisons.")

    precision = result.get("precision")
    lines.extend(["", "## MDE and power", ""])
    if precision:
        lines.extend(
            [
                f"- Approximate detectable absolute effect: {precision['estimated_mde']:.4g}",
                f"- Configured planned MDE: {precision['planned_mde']:.4g}",
                f"- Approximate power at planned MDE: {precision['power_at_planned_mde']:.3f}",
                "- These normal-approximation values are planning diagnostics, not "
                "evidence that a non-significant result means no effect.",
            ]
        )
    else:
        lines.append("Not calculated: no binary primary metric is configured.")
    if result.get("reason"):
        lines.extend(["", "## Pipeline decision", "", result["reason"]])
    lines.extend(
        [
            "",
            "## Interpretation note",
            "",
            "This report is an analytical artifact, not a business recommendation. "
            "Review the experiment design, SRM status, guardrails, and practical "
            "effect size before making a decision.",
            "",
        ]
    )
    return "\n".join(lines)


def write_json(path: str | Path, value: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_alert(path: str | Path, result: dict, experiment_id: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    status = result.get("status", "failed")
    reason = result.get("reason") or "Analysis completed; review the report."
    target.write_text(
        f"experiment_id={experiment_id}\nstatus={status}\nmessage={reason}\n",
        encoding="utf-8",
    )

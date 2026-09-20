"""Build manuscript-facing criticality results without touching confirmation endpoints.

The figure and summary use the exploratory seeds 0--9 output only.  The
preregistered seeds 10--29 contribute only their property-gate status because
the frozen protocol stopped before endpoint analysis.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


PRIMARY_MODELS = ["lr", "iforest", "hgb", "pca", "ae"]
ALL_MODELS = ["lr", "dtree", "iforest", "hgb", "pca", "ae"]
MODEL_LABELS = {
    "lr": "Logistic regression",
    "dtree": "Decision tree",
    "iforest": "Isolation forest",
    "hgb": "HGB",
    "pca": "PCA",
    "ae": "Autoencoder",
}
SCENARIOS = ["platform_survival", "payload_first"]


def t_summary(values: pd.Series | np.ndarray) -> dict[str, float | int]:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or array.size < 2 or not np.isfinite(array).all():
        raise ValueError("A finite one-dimensional sample with n >= 2 is required")
    mean = float(np.mean(array))
    sem = float(stats.sem(array))
    half_width = float(stats.t.ppf(0.975, array.size - 1) * sem)
    return {
        "mean": mean,
        "ci_95_low": mean - half_width,
        "ci_95_high": mean + half_width,
        "n_seeds": int(array.size),
    }


def observed_seed_gains(policy: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    subset = policy[
        policy["model"].isin(models)
        & policy["scenario"].isin(SCENARIOS)
        & policy["policy"].isin(["score_only", "occlusion_context"])
    ].copy()
    pivot = subset.pivot(
        index=["seed", "model", "scenario"],
        columns="policy",
        values="muc_auc_0_40",
    ).reset_index()
    pivot["gain"] = pivot["occlusion_context"] - pivot["score_only"]
    expected = 10 * len(models) * len(SCENARIOS)
    if len(pivot) != expected:
        raise RuntimeError(f"Observed gain grid is incomplete: {len(pivot)} != {expected}")
    return (
        pivot.groupby(["seed", "scenario"], as_index=False)["gain"]
        .mean()
        .sort_values(["seed", "scenario"])
    )


def scenario_and_contrast_summaries(seed_gains: pd.DataFrame) -> dict[str, dict]:
    wide = seed_gains.pivot(index="seed", columns="scenario", values="gain")
    platform = wide["platform_survival"]
    payload = wide["payload_first"]
    return {
        "platform_survival": t_summary(platform),
        "payload_first": t_summary(payload),
        "platform_minus_payload": t_summary(platform - payload),
    }


def information_summaries(
    observed: pd.DataFrame, utility_null: pd.DataFrame
) -> dict[str, dict]:
    null_primary = utility_null[
        utility_null["model"].isin(PRIMARY_MODELS)
        & utility_null["scenario"].isin(SCENARIOS)
    ].copy()
    null_seed = (
        null_primary.groupby(["seed", "scenario"], as_index=False)["gain"]
        .mean()
        .rename(columns={"gain": "null_gain"})
    )
    merged = observed.merge(null_seed, on=["seed", "scenario"], validate="one_to_one")
    merged["information_gain"] = merged["gain"] - merged["null_gain"]
    wide = merged.pivot(index="seed", columns="scenario", values="information_gain")
    platform = wide["platform_survival"]
    payload = wide["payload_first"]
    return {
        "platform_survival": t_summary(platform),
        "payload_first": t_summary(payload),
        "platform_minus_payload": t_summary(platform - payload),
        "null_mean": {
            scenario: float(
                merged.loc[merged["scenario"] == scenario, "null_gain"].mean()
            )
            for scenario in SCENARIOS
        },
    }


def build_figure(cell_decisions: pd.DataFrame, output_base: Path) -> None:
    plot = cell_decisions[cell_decisions["scenario"].isin(SCENARIOS)].copy()
    positions = np.arange(len(ALL_MODELS))[::-1]
    limits = (
        float(plot["t_ci_low"].min()) - 0.015,
        float(plot["t_ci_high"].max()) + 0.015,
    )
    colors = {
        "platform_survival": "#00796B",
        "payload_first": "#C45A36",
    }
    titles = {
        "platform_survival": "Platform-survival utility",
        "payload_first": "Payload-first utility",
    }

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.titlesize": 10.5,
            "axes.labelsize": 9.5,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 9.0,
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 3.25), sharey=True)

    for axis, scenario in zip(axes, SCENARIOS, strict=True):
        rows = plot[plot["scenario"] == scenario].set_index("model").loc[ALL_MODELS]
        for y, (model, row) in zip(positions, rows.iterrows(), strict=True):
            mean = float(row["gain_mean"])
            low = float(row["t_ci_low"])
            high = float(row["t_ci_high"])
            is_tree = model == "dtree"
            color = "#6F777B" if is_tree else colors[scenario]
            axis.errorbar(
                mean,
                y,
                xerr=np.array([[mean - low], [high - mean]]),
                fmt="o",
                markersize=5.8,
                markerfacecolor="white" if is_tree else color,
                markeredgecolor=color,
                markeredgewidth=1.3,
                ecolor=color,
                elinewidth=1.25,
                capsize=2.8,
                zorder=3,
            )
        axis.axvline(0.0, color="#444444", linestyle=(0, (3, 3)), linewidth=0.9)
        axis.set_xlim(*limits)
        axis.set_title(titles[scenario], pad=7)
        axis.set_xlabel("MUC-AUC$_{0.40}$ gain over score-only")
        axis.grid(axis="x", color="#D6D9DB", linewidth=0.6, alpha=0.8)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.tick_params(axis="y", length=0)

    axes[0].set_yticks(positions, [MODEL_LABELS[m] for m in ALL_MODELS])
    fig.subplots_adjust(left=0.235, right=0.985, top=0.90, bottom=0.27, wspace=0.30)
    for panel, axis in zip(("(a)", "(b)"), axes, strict=True):
        position = axis.get_position()
        fig.text(
            position.x0 + position.width / 2,
            0.045,
            panel,
            ha="center",
            va="bottom",
            fontsize=9.5,
        )
    output_base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_base.with_suffix(".png"), dpi=600, facecolor="white")
    fig.savefig(output_base.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    project = args.project_root.resolve()
    output = args.output_root.resolve()
    discovery = project / "experiments" / "2026-08-26_codex_local_criticality_uplift_discovery_v3b" / "metrics"
    confirmation = project / "experiments" / "2026-08-26_codex_local_criticality_heterogeneity_confirmation_v1_1" / "metrics"

    policy = pd.read_csv(discovery / "policy_summary.csv")
    null = pd.read_csv(discovery / "utility_permutation_null.csv")
    cells = pd.read_csv(discovery / "cell_decisions.csv")
    property_tests = json.loads((confirmation / "property_tests.json").read_text(encoding="utf-8"))
    failure = json.loads((confirmation / "confirmatory_failure.json").read_text(encoding="utf-8"))

    primary_gains = observed_seed_gains(policy, PRIMARY_MODELS)
    six_model_gains = observed_seed_gains(policy, ALL_MODELS)
    summary = {
        "schema_version": 1,
        "evidence_boundary": {
            "exploratory_endpoint_seeds": list(range(10)),
            "preregistered_confirmation_seeds": list(range(10, 30)),
            "confirmation_endpoints_analyzed": False,
        },
        "exploratory_primary_five_model_raw_gain": scenario_and_contrast_summaries(primary_gains),
        "exploratory_six_model_raw_gain_sensitivity": scenario_and_contrast_summaries(six_model_gains),
        "exploratory_primary_five_model_above_null_information": information_summaries(primary_gains, null),
        "preregistered_confirmation": {
            "status": failure["status"],
            "property_checks_passed": int(property_tests["n_checks"] - len(property_tests["failed"])),
            "property_checks_total": int(property_tests["n_checks"]),
            "failed_property_checks": property_tests["failed"],
            "failed_cell_value": 9,
            "required_minimum": 10,
            "endpoint_analysis_performed": bool(failure["endpoint_analysis_performed"]),
            "rescue_change_performed": bool(failure["rescue_change_performed"]),
            "release_tag": failure["release_tag"],
            "release_commit": failure["release_commit"],
            "release_url": failure["release_url"],
        },
    }

    output.mkdir(parents=True, exist_ok=True)
    (output / "criticality_manuscript_summary_v4.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    build_figure(cells, output / "fig_prioritization")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

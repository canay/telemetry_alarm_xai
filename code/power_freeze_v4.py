"""Freeze the joint-power calculation for the five-endpoint V4 IU rule.

The discovery inputs are seed-level and exploratory.  The calculation inflates
their full covariance matrix by the largest one-sided 95% upper-SD multiplier
and simulates the exact joint Student-t decision.  It is a planning artifact,
not confirmatory evidence.

Operation: f07-criticality-v4-pre-freeze-repair-20260826
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2

from criticality_analysis_v4 import confirmatory_decision


PRIMARY_MODELS = ("lr", "iforest", "hgb", "pca", "ae")
SCENARIOS = ("platform_survival", "payload_first")
POWER_SEED = 20_260_826 + 44_000
OUTER = 20_000
TARGET = 0.80


def endpoint_matrix(metrics_dir: Path) -> pd.DataFrame:
    policy = pd.read_csv(metrics_dir / "policy_summary.csv")
    utility_null = pd.read_csv(metrics_dir / "utility_permutation_null.csv")
    policy = policy[
        policy["model"].isin(PRIMARY_MODELS)
        & policy["scenario"].isin(SCENARIOS)
        & policy["policy"].isin(("score_only", "occlusion_context"))
    ]
    pivot = policy.pivot(
        index=["seed", "model", "scenario"],
        columns="policy",
        values="muc_auc_0_40",
    ).reset_index()
    pivot["gain"] = pivot["occlusion_context"] - pivot["score_only"]
    raw = pivot.groupby(["seed", "scenario"])["gain"].mean().unstack()
    null = (
        utility_null[
            utility_null["model"].isin(PRIMARY_MODELS)
            & utility_null["scenario"].isin(SCENARIOS)
        ]
        .groupby(["seed", "scenario"])["gain"]
        .mean()
        .unstack()
    )
    result = pd.DataFrame(index=raw.index)
    result["platform_raw"] = raw["platform_survival"]
    result["payload_harm_raw"] = -raw["payload_first"]
    result["platform_information"] = (
        raw["platform_survival"] - null["platform_survival"]
    )
    result["payload_information"] = raw["payload_first"] - null["payload_first"]
    result["scenario_contrast_raw"] = (
        result["platform_raw"] + result["payload_harm_raw"]
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-n", type=int, default=12)
    parser.add_argument("--maximum-n", type=int, default=80)
    args = parser.parse_args()

    frame = endpoint_matrix(args.metrics_dir)
    base_names = (
        "platform_raw",
        "payload_harm_raw",
        "platform_information",
        "payload_information",
    )
    base = frame.loc[:, base_names].to_numpy(dtype=float)
    mean = base.mean(axis=0)
    covariance = np.cov(base, rowvar=False, ddof=1)
    observed_sd = np.sqrt(np.diag(covariance))
    sd_upper_multiplier = math.sqrt(
        (len(base) - 1) / chi2.ppf(0.05, len(base) - 1)
    )
    conservative_covariance = covariance * sd_upper_multiplier**2
    rng = np.random.default_rng(POWER_SEED)
    curve: list[dict] = []
    recommended_n: int | None = None
    for n in range(args.minimum_n, args.maximum_n + 1):
        passes = 0
        for _ in range(OUTER):
            sample = rng.multivariate_normal(
                mean, conservative_covariance, size=n, check_valid="raise"
            )
            endpoints = (
                sample[:, 0],
                sample[:, 1],
                sample[:, 0] + sample[:, 1],
                sample[:, 2],
                sample[:, 3],
            )
            passes += int(all(confirmatory_decision(values)["pass"] for values in endpoints))
        power = passes / OUTER
        curve.append({"n": n, "joint_power": power})
        print(f"V4_JOINT_POWER n={n} power={power:.4f}", flush=True)
        if power >= TARGET:
            recommended_n = n
            break

    output = {
        "schema_version": 1,
        "status": "TARGET_REACHED" if recommended_n is not None else "TARGET_NOT_REACHED",
        "decision_rule": "all five one-sided Student-t lower bounds exceed zero",
        "discovery_seed_count": int(len(base)),
        "base_endpoint_names": list(base_names),
        "base_endpoint_means": dict(zip(base_names, mean.tolist())),
        "base_endpoint_observed_sd": dict(zip(base_names, observed_sd.tolist())),
        "sd_upper_multiplier": sd_upper_multiplier,
        "covariance_inflation": sd_upper_multiplier**2,
        "simulation_seed": POWER_SEED,
        "outer_simulations_per_n": OUTER,
        "target_joint_power": TARGET,
        "recommended_n": recommended_n,
        "curve": curve,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(args.output)
    if recommended_n is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

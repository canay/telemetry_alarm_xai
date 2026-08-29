"""Freeze V5 joint power and predictive assurance for the five-endpoint IU rule.

Discovery seeds are used only for prospective planning.  The fixed-mean curve
matches the public V1.1 procedure on the new pooled-queue estimand.  The
predictive-assurance curve additionally propagates uncertainty in the
four-dimensional discovery mean before simulating a future confirmation.

Operation: f07-v5-power-mismatch-independent-review-20260830
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2, t


PRIMARY_MODELS = ("lr", "iforest", "hgb", "pca", "ae")
SCENARIOS = ("platform_survival", "payload_first")
BASE_ENDPOINTS = (
    "platform_raw",
    "payload_harm_raw",
    "platform_information",
    "payload_information",
)
POWER_SEED = 20_260_830 + 55_000
OUTER = 20_000
TARGET = 0.80
PROTOCOL_FLOOR_N = 20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    if not raw.index.equals(null.index):
        raise RuntimeError("policy and utility-null seed populations differ")
    result = pd.DataFrame(index=raw.index)
    result["platform_raw"] = raw["platform_survival"]
    result["payload_harm_raw"] = -raw["payload_first"]
    result["platform_information"] = (
        raw["platform_survival"] - null["platform_survival"]
    )
    result["payload_information"] = (
        raw["payload_first"] - null["payload_first"]
    )
    result["scenario_contrast_raw"] = (
        result["platform_raw"] + result["payload_harm_raw"]
    )
    return result


def joint_pass_rate(samples: np.ndarray) -> float:
    """Apply the exact five one-sided Student-t lower-bound conditions."""

    if samples.ndim != 3 or samples.shape[2] != 4:
        raise ValueError("samples must have shape (simulation, n, 4)")
    n = samples.shape[1]
    if n < 2:
        return 0.0
    endpoints = (
        samples[:, :, 0],
        samples[:, :, 1],
        samples[:, :, 0] + samples[:, :, 1],
        samples[:, :, 2],
        samples[:, :, 3],
    )
    critical = float(t.ppf(0.95, n - 1))
    joint = np.ones(samples.shape[0], dtype=bool)
    for values in endpoints:
        mean = values.mean(axis=1)
        sd = values.std(axis=1, ddof=1)
        lower = mean - critical * sd / math.sqrt(n)
        joint &= lower > 0
    return float(joint.mean())


def simulate_curve(
    mean: np.ndarray,
    covariance: np.ndarray,
    conservative_covariance: np.ndarray,
    discovery_n: int,
    minimum_n: int,
    maximum_n: int,
) -> tuple[list[dict], list[dict], int | None, int | None]:
    fixed_curve: list[dict] = []
    predictive_curve: list[dict] = []
    fixed_recommendation: int | None = None
    predictive_recommendation: int | None = None
    for n in range(minimum_n, maximum_n + 1):
        fixed_rng = np.random.default_rng(
            np.random.SeedSequence([POWER_SEED, n, 1])
        )
        fixed_samples = fixed_rng.multivariate_normal(
            mean,
            conservative_covariance,
            size=(OUTER, n),
            check_valid="raise",
        )
        fixed_power = joint_pass_rate(fixed_samples)
        fixed_curve.append({"n": n, "joint_power": fixed_power})
        if fixed_recommendation is None and fixed_power >= TARGET:
            fixed_recommendation = n

        predictive_rng = np.random.default_rng(
            np.random.SeedSequence([POWER_SEED, n, 2])
        )
        latent_mean = predictive_rng.multivariate_normal(
            mean,
            covariance / discovery_n,
            size=OUTER,
            check_valid="raise",
        )
        future_noise = predictive_rng.multivariate_normal(
            np.zeros(4, dtype=float),
            conservative_covariance,
            size=(OUTER, n),
            check_valid="raise",
        )
        predictive_samples = latent_mean[:, None, :] + future_noise
        predictive_power = joint_pass_rate(predictive_samples)
        predictive_curve.append({"n": n, "joint_assurance": predictive_power})
        if predictive_recommendation is None and predictive_power >= TARGET:
            predictive_recommendation = n

        print(
            f"V5_JOINT_POWER n={n} fixed={fixed_power:.4f} "
            f"predictive={predictive_power:.4f}",
            flush=True,
        )
        if fixed_recommendation is not None and predictive_recommendation is not None:
            break
    return (
        fixed_curve,
        predictive_curve,
        fixed_recommendation,
        predictive_recommendation,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-dir", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-n", type=int, default=3)
    parser.add_argument("--maximum-n", type=int, default=80)
    args = parser.parse_args()
    if args.minimum_n < 3 or args.maximum_n < args.minimum_n:
        raise ValueError("power grid must satisfy 3 <= minimum-n <= maximum-n")

    manifest = json.loads(args.run_manifest.read_text(encoding="utf-8"))
    if manifest.get("status") != "DISCOVERY_COMPLETE":
        raise RuntimeError("source V5 discovery run is not complete")
    if manifest.get("mode") != "discovery" or manifest.get("seeds") != list(range(10)):
        raise RuntimeError("source power population must be discovery seeds 0-9")
    if manifest.get("n_test_replicates") != 7:
        raise RuntimeError("source power population must use seven test replicates")

    frame = endpoint_matrix(args.metrics_dir)
    if frame.index.tolist() != list(range(10)):
        raise RuntimeError("endpoint matrix seed set is not exactly 0-9")
    base = frame.loc[:, BASE_ENDPOINTS].to_numpy(dtype=float)
    mean = base.mean(axis=0)
    covariance = np.cov(base, rowvar=False, ddof=1)
    observed_sd = np.sqrt(np.diag(covariance))
    sd_upper_multiplier = math.sqrt(
        (len(base) - 1) / chi2.ppf(0.05, len(base) - 1)
    )
    conservative_covariance = covariance * sd_upper_multiplier**2
    (
        fixed_curve,
        predictive_curve,
        fixed_n,
        predictive_n,
    ) = simulate_curve(
        mean,
        covariance,
        conservative_covariance,
        len(base),
        args.minimum_n,
        args.maximum_n,
    )
    recommendations = [value for value in (fixed_n, predictive_n) if value is not None]
    recommended_n = max(recommendations) if len(recommendations) == 2 else None
    confirmation_n = max(PROTOCOL_FLOOR_N, recommended_n) if recommended_n else None

    output = {
        "schema_version": 2,
        "status": "TARGET_REACHED" if recommended_n is not None else "TARGET_NOT_REACHED",
        "not_confirmatory_evidence": True,
        "analysis_schema_version": manifest.get("schema_version"),
        "source_run_manifest_sha256": sha256(args.run_manifest),
        "source_run_contract_sha256": manifest.get("run_contract_sha256"),
        "source_metrics_sha256": {
            name: sha256(args.metrics_dir / name)
            for name in ("policy_summary.csv", "utility_permutation_null.csv")
        },
        "discovery_seeds": list(range(10)),
        "discovery_seed_count": len(base),
        "primary_models": list(PRIMARY_MODELS),
        "primary_estimand": "pooled episode queue after within-replicate segmentation",
        "test_replicates_per_seed": 7,
        "decision_rule": "all five one-sided Student-t lower bounds exceed zero",
        "base_endpoint_names": list(BASE_ENDPOINTS),
        "base_endpoint_means": dict(zip(BASE_ENDPOINTS, mean.tolist())),
        "base_endpoint_observed_sd": dict(zip(BASE_ENDPOINTS, observed_sd.tolist())),
        "base_endpoint_covariance": covariance.tolist(),
        "sd_upper_multiplier": sd_upper_multiplier,
        "covariance_inflation": sd_upper_multiplier**2,
        "predictive_mean_model": "latent four-endpoint mean ~ N(discovery mean, observed covariance / 10)",
        "simulation_seed": POWER_SEED,
        "outer_simulations_per_n": OUTER,
        "target_joint_power_or_assurance": TARGET,
        "minimum_n_searched": args.minimum_n,
        "maximum_n_searched": args.maximum_n,
        "fixed_mean_curve": fixed_curve,
        "predictive_assurance_curve": predictive_curve,
        "fixed_mean_recommended_n": fixed_n,
        "predictive_assurance_recommended_n": predictive_n,
        "recommended_n": recommended_n,
        "protocol_floor_n": PROTOCOL_FLOOR_N,
        "confirmation_n": confirmation_n,
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

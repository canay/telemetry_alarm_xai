#!/usr/bin/env python3
"""Deterministic Round B summaries from frozen signature and priority artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


SIGNATURE_INPUTS = {
    "kddcup99": Path(
        "experiments/2026-07-28_codex_local_kdd_signature_stability_repair/"
        "processed_outputs/second_transfer_benchmark/feature_signature_audit.csv"
    ),
    "opssat_ad": Path(
        "experiments/2026-07-28_codex_local_opssat_signature_repair/"
        "processed_outputs/opssat_transfer_benchmark/feature_signature_audit.csv"
    ),
}

PRIORITY_INPUTS = {
    "primary_5_seed": Path(
        "experiments/2026-07-28_codex_local_cplus_statistics_recompute/"
        "metrics/q1_audit_revision/priority_ablation_seed.csv"
    ),
    "sensitivity_10_seed": Path(
        "experiments/2026-07-28_codex_local_cplus_statistics_recompute/"
        "metrics/q1_seed_expansion/priority_ablation_seed.csv"
    ),
}

PRIORITY_CI_INPUTS = {
    "primary_5_seed": Path(
        "experiments/2026-07-28_codex_local_cplus_statistics_recompute/"
        "metrics/q1_audit_revision/priority_gain_bootstrap_ci.csv"
    ),
    "sensitivity_10_seed": Path(
        "experiments/2026-07-28_codex_local_cplus_statistics_recompute/"
        "metrics/q1_seed_expansion/priority_gain_bootstrap_ci.csv"
    ),
}

ESTIMATOR_METADATA = {
    ("kddcup99", "logistic"): (
        "permutation importance using average precision",
        "41 original KDDCup99 tabular features",
    ),
    ("kddcup99", "random_forest"): (
        "permutation importance using average precision",
        "41 original KDDCup99 tabular features",
    ),
    ("kddcup99", "hgb"): (
        "permutation importance using average precision",
        "41 original KDDCup99 tabular features",
    ),
    ("kddcup99", "isolation_forest"): (
        "mean absolute raw anomaly-score change after feature permutation",
        "41 original KDDCup99 tabular features",
    ),
    ("opssat_ad", "logistic"): (
        "normalized absolute fitted coefficients",
        "preprocessed numeric plus one-hot categorical features",
    ),
    ("opssat_ad", "random_forest"): (
        "normalized intrinsic impurity-based feature importance",
        "preprocessed numeric plus one-hot categorical features",
    ),
    ("opssat_ad", "hgb"): (
        "normalized mean absolute raw score change after feature permutation",
        "20 original OPSSAT-AD extracted features",
    ),
    ("opssat_ad", "isolation_forest"): (
        "normalized mean absolute raw anomaly-score change after feature permutation",
        "20 original OPSSAT-AD extracted features",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def validate_signature_input(frame: pd.DataFrame, path: Path) -> None:
    required = {"feature", "importance", "seed", "model"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path} misses columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{path} is empty")
    if not np.isfinite(frame["importance"].to_numpy(dtype=float)).all():
        raise ValueError(f"{path} contains non-finite importance values")


def signature_pair_audit(dataset: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pair_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for model, model_frame in frame.groupby("model", sort=True):
        vectors: dict[int, pd.Series] = {}
        for seed, seed_frame in model_frame.groupby("seed", sort=True):
            vectors[int(seed)] = seed_frame.groupby("feature")["importance"].sum()
        seeds = sorted(vectors)
        estimator, feature_space = ESTIMATOR_METADATA[(dataset, str(model))]
        for position, seed_a in enumerate(seeds):
            for seed_b in seeds[position + 1 :]:
                features = vectors[seed_a].index.union(vectors[seed_b].index)
                vector_a = vectors[seed_a].reindex(features, fill_value=0.0).to_numpy(dtype=float)
                vector_b = vectors[seed_b].reindex(features, fill_value=0.0).to_numpy(dtype=float)
                norm_a = float(np.linalg.norm(vector_a))
                norm_b = float(np.linalg.norm(vector_b))
                if norm_a == 0.0 or norm_b == 0.0:
                    cosine = np.nan
                    status = "degenerate"
                    if norm_a == 0.0 and norm_b == 0.0:
                        reason = "both_zero_norm"
                    elif norm_a == 0.0:
                        reason = "seed_a_zero_norm"
                    else:
                        reason = "seed_b_zero_norm"
                else:
                    cosine = float(np.dot(vector_a, vector_b) / (norm_a * norm_b))
                    status = "valid"
                    reason = ""
                pair_rows.append(
                    {
                        "dataset": dataset,
                        "model": model,
                        "seed_a": seed_a,
                        "seed_b": seed_b,
                        "norm_a": norm_a,
                        "norm_b": norm_b,
                        "cosine": cosine,
                        "pair_status": status,
                        "degenerate_reason": reason,
                        "signature_estimator": estimator,
                        "feature_space": feature_space,
                    }
                )
        model_pairs = [row for row in pair_rows if row["dataset"] == dataset and row["model"] == model]
        valid = np.asarray(
            [float(row["cosine"]) for row in model_pairs if row["pair_status"] == "valid"],
            dtype=float,
        )
        summary_rows.append(
            {
                "dataset": dataset,
                "model": model,
                "signature_estimator": estimator,
                "feature_space": feature_space,
                "n_seeds": len(seeds),
                "n_pairs_total": len(model_pairs),
                "n_pairs_valid": len(valid),
                "n_pairs_degenerate": len(model_pairs) - len(valid),
                "mean_signature_cosine": float(valid.mean()) if len(valid) else np.nan,
                "population_sd_signature_cosine": float(valid.std(ddof=0)) if len(valid) else np.nan,
                "sample_sd_signature_cosine": float(valid.std(ddof=1)) if len(valid) > 1 else np.nan,
            }
        )
    return pd.DataFrame(pair_rows), pd.DataFrame(summary_rows)


def priority_summaries(
    scope: str,
    frame: pd.DataFrame,
    ci_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"model", "seed", "variant", "ndcg10", "ndcg_gain_vs_score"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{scope} priority input misses columns: {sorted(missing)}")
    selected = frame.loc[
        frame["variant"].isin(["score_only", "additive_full", "multiplicative_stability"])
    ].copy()
    grouped = (
        selected.groupby(["model", "variant"], as_index=False)
        .agg(
            ndcg10_mean=("ndcg10", "mean"),
            ndcg10_sample_sd=("ndcg10", lambda values: values.std(ddof=1)),
            ndcg_gain_mean=("ndcg_gain_vs_score", "mean"),
            ndcg_gain_sample_sd=("ndcg_gain_vs_score", lambda values: values.std(ddof=1)),
            n_seeds=("seed", "nunique"),
        )
        .assign(scope=scope)
    )
    additive = selected.loc[selected["variant"] == "additive_full"].copy()
    additive = additive.merge(
        ci_frame[["model", "ndcg_ci_low", "ndcg_ci_high", "n_seeds"]],
        on="model",
        suffixes=("", "_ci"),
        validate="many_to_one",
    )
    attenuation = (
        additive.groupby("model", as_index=False)
        .agg(
            ndcg_gain_mean=("ndcg_gain_vs_score", "mean"),
            ndcg_gain_sample_sd=("ndcg_gain_vs_score", lambda values: values.std(ddof=1)),
            ndcg_ci_low=("ndcg_ci_low", "first"),
            ndcg_ci_high=("ndcg_ci_high", "first"),
            n_seeds=("seed", "nunique"),
        )
        .assign(scope=scope)
    )
    return grouped, attenuation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=False)

    input_hashes: dict[str, str] = {}
    pair_frames: list[pd.DataFrame] = []
    signature_summaries: list[pd.DataFrame] = []
    for dataset, relative_path in SIGNATURE_INPUTS.items():
        path = base_dir / relative_path
        input_hashes[str(relative_path).replace("\\", "/")] = sha256(path)
        frame = pd.read_csv(path)
        validate_signature_input(frame, path)
        pairs, summary = signature_pair_audit(dataset, frame)
        pair_frames.append(pairs)
        signature_summaries.append(summary)

    pair_audit = pd.concat(pair_frames, ignore_index=True)
    signature_summary = pd.concat(signature_summaries, ignore_index=True)
    pair_audit.to_csv(out_dir / "signature_pair_audit.csv", index=False)
    signature_summary.to_csv(out_dir / "signature_pair_summary.csv", index=False)

    priority_summary_frames: list[pd.DataFrame] = []
    attenuation_frames: list[pd.DataFrame] = []
    priority_frames: dict[str, pd.DataFrame] = {}
    for scope, relative_path in PRIORITY_INPUTS.items():
        path = base_dir / relative_path
        ci_path = base_dir / PRIORITY_CI_INPUTS[scope]
        input_hashes[str(relative_path).replace("\\", "/")] = sha256(path)
        input_hashes[str(PRIORITY_CI_INPUTS[scope]).replace("\\", "/")] = sha256(ci_path)
        frame = pd.read_csv(path)
        ci_frame = pd.read_csv(ci_path)
        priority_frames[scope] = frame
        summary, attenuation = priority_summaries(scope, frame, ci_frame)
        priority_summary_frames.append(summary)
        attenuation_frames.append(attenuation)

    priority_summary = pd.concat(priority_summary_frames, ignore_index=True)
    attenuation_summary = pd.concat(attenuation_frames, ignore_index=True)
    priority_summary.to_csv(out_dir / "priority_ndcg_summary.csv", index=False)
    attenuation_summary.to_csv(out_dir / "priority_attenuation_summary.csv", index=False)

    iforest_primary = priority_frames["primary_5_seed"].loc[
        (priority_frames["primary_5_seed"]["model"] == "iforest")
        & (priority_frames["primary_5_seed"]["variant"] == "additive_full"),
        ["seed", "ndcg10", "ndcg_gain_vs_score"],
    ].sort_values("seed")
    if len(iforest_primary) != 5:
        raise ValueError(f"Expected five primary isolation-forest seeds, found {len(iforest_primary)}")
    positive_sum = float(iforest_primary["ndcg_gain_vs_score"].clip(lower=0.0).sum())
    max_row = iforest_primary.loc[iforest_primary["ndcg_gain_vs_score"].idxmax()]
    iforest_primary.to_csv(out_dir / "iforest_primary_additive_seed_gains.csv", index=False)

    derived_summary = {
        "operation_id": "round-b-approved-remediation-20260730",
        "analysis_class": "deterministic summaries from frozen artifacts; no model refit",
        "input_sha256": input_hashes,
        "signature_cosine_interpretation": (
            "Within-model cross-seed repeatability only; absolute magnitudes are not compared "
            "across model-specific estimators or feature spaces."
        ),
        "signature_sd_convention": "population SD (ddof=0), matching the frozen transfer scripts",
        "priority_sd_convention": "sample SD (ddof=1) across detector seeds",
        "iforest_primary_5_seed": {
            "mean_additive_gain": float(iforest_primary["ndcg_gain_vs_score"].mean()),
            "sample_sd_additive_gain": float(iforest_primary["ndcg_gain_vs_score"].std(ddof=1)),
            "max_gain_seed": int(max_row["seed"]),
            "max_gain": float(max_row["ndcg_gain_vs_score"]),
            "positive_gain_sum": positive_sum,
            "max_share_of_positive_gain": (
                float(max_row["ndcg_gain_vs_score"]) / positive_sum if positive_sum > 0 else None
            ),
        },
    }
    with (out_dir / "derived_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(derived_summary, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    outputs = sorted(path for path in out_dir.iterdir() if path.is_file())
    output_hashes = {path.name: sha256(path) for path in outputs}
    with (out_dir / "output_hashes.json").open("w", encoding="utf-8") as handle:
        json.dump(output_hashes, handle, indent=2)
        handle.write("\n")

    print(f"ROUND_B_DERIVED_EVIDENCE_OK {out_dir}")


if __name__ == "__main__":
    main()

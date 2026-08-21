#!/usr/bin/env python3
"""Second real transfer benchmark for SCI-f07 telemetry alarm XAI."""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.datasets import fetch_kddcup99
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def resource_snapshot() -> dict:
    snap = {"timestamp_utc": utc_now(), "platform": platform.platform()}
    try:
        import psutil  # type: ignore

        snap.update(
            {
                "cpu_percent": psutil.cpu_percent(interval=0.2),
                "virtual_memory_percent": psutil.virtual_memory().percent,
                "rss_mb": psutil.Process(os.getpid()).memory_info().rss / 1_000_000,
            }
        )
    except Exception as exc:
        snap["psutil_error"] = repr(exc)
    return snap


class TimingLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def stage(self, name: str, **meta):
        start = time.perf_counter()
        rec = {"stage": name, "start_utc": utc_now(), **meta}
        try:
            yield
            rec["status"] = "ok"
        except Exception as exc:
            rec["status"] = "error"
            rec["error"] = repr(exc)
            raise
        finally:
            rec["end_utc"] = utc_now()
            rec["wall_seconds"] = time.perf_counter() - start
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")


def decode_value(v):
    if isinstance(v, bytes):
        return v.decode("latin1")
    return v


def load_kdd(seed: int, max_rows: int) -> tuple[pd.DataFrame, np.ndarray]:
    try:
        bunch = fetch_kddcup99(subset="SA", percent10=True, shuffle=True, random_state=seed, as_frame=True)
        x = bunch.data.copy()
        y_raw = bunch.target
    except TypeError:
        bunch = fetch_kddcup99(subset="SA", percent10=True, shuffle=True, random_state=seed)
        x = pd.DataFrame(bunch.data)
        y_raw = bunch.target
    if hasattr(x, "map"):
        x = x.map(decode_value)
    else:
        x = x.applymap(decode_value)
    y_series = pd.Series(y_raw).map(decode_value)
    y = (y_series != "normal.").astype(int).to_numpy()
    if max_rows > 0 and len(x) > max_rows:
        rng = np.random.default_rng(seed)
        idx = []
        for cls in [0, 1]:
            cls_idx = np.where(y == cls)[0]
            take = min(len(cls_idx), max_rows // 2)
            idx.extend(rng.choice(cls_idx, size=take, replace=False).tolist())
        idx = np.array(idx)
        rng.shuffle(idx)
        x = x.iloc[idx].reset_index(drop=True)
        y = y[idx]
    x.columns = [f"f{i}" if not isinstance(c, str) else str(c) for i, c in enumerate(x.columns)]
    return x, y


def one_hot_encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False, min_frequency=5)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def split_columns(x: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    numeric = []
    categorical = []
    for col in x.columns:
        converted = pd.to_numeric(x[col], errors="coerce")
        if converted.notna().mean() > 0.98:
            x[col] = converted.fillna(converted.median())
            numeric.append(col)
        else:
            x[col] = x[col].astype(str)
            categorical.append(col)
    return list(x.columns), numeric, categorical


def make_preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("num", StandardScaler(), numeric),
            ("cat", one_hot_encoder(), categorical),
        ],
        remainder="drop",
        sparse_threshold=0.0,
    )


def model_score(model, x: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return model.predict_proba(x)[:, 1]
    score = -model.decision_function(x)
    return score.astype(float)


def normalize_score(score: np.ndarray) -> np.ndarray:
    lo = float(np.min(score))
    hi = float(np.max(score))
    return (score - lo) / max(1e-8, hi - lo)


def precision_at_fraction(y: np.ndarray, score: np.ndarray, frac: float) -> float:
    n = max(1, int(len(y) * frac))
    idx = np.argsort(score)[::-1][:n]
    return float(np.mean(y[idx]))


def signature_vector(model, x: pd.DataFrame, y: np.ndarray, features: list[str], seed: int, supervised: bool) -> pd.DataFrame:
    if supervised:
        imp = permutation_importance(
            model,
            x,
            y,
            scoring="average_precision",
            n_repeats=3,
            random_state=seed,
            n_jobs=1,
        )
        vals = np.maximum(imp.importances_mean, 0.0)
        return pd.DataFrame({"feature": features, "importance": vals})
    base = model_score(model, x)
    rng = np.random.default_rng(seed)
    rows = []
    for feat in features:
        xp = x.copy()
        xp[feat] = rng.permutation(xp[feat].to_numpy())
        rows.append({"feature": feat, "importance": float(np.mean(np.abs(base - model_score(model, xp))))})
    return pd.DataFrame(rows)


def explanation_concentration(x: pd.DataFrame, numeric: list[str], train_numeric: pd.DataFrame, signature: pd.DataFrame) -> np.ndarray:
    if not numeric:
        return np.zeros(len(x))
    scaler = StandardScaler().fit(train_numeric[numeric])
    z = np.abs(scaler.transform(x[numeric]))
    weights = signature.set_index("feature")["importance"].reindex(numeric).fillna(0.0).to_numpy()
    if np.sum(weights) <= 0:
        weights = np.ones_like(weights)
    contrib = z * weights.reshape(1, -1)
    total = contrib.sum(axis=1) + 1e-8
    top3 = np.sort(contrib, axis=1)[:, -min(3, contrib.shape[1]) :].sum(axis=1)
    return top3 / total


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom <= 0:
        return np.nan
    return float(np.dot(a, b) / denom)


def summarize_signature_stability(sig_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model_name, group in sig_df.groupby("model"):
        vectors = []
        all_features = sorted(group["feature"].unique())
        for _seed, seed_group in group.groupby("seed"):
            vectors.append(
                seed_group.groupby("feature")["importance"]
                .sum()
                .reindex(all_features, fill_value=0.0)
                .to_numpy()
            )
        sims = [
            cosine(vectors[i], vectors[j])
            for i in range(len(vectors))
            for j in range(i + 1, len(vectors))
        ]
        valid = np.asarray([value for value in sims if np.isfinite(value)], dtype=float)
        rows.append(
            {
                "model": model_name,
                "n_pairs": int(len(valid)),
                "n_pairs_total": int(len(sims)),
                "n_pairs_valid": int(len(valid)),
                "n_pairs_degenerate": int(len(sims) - len(valid)),
                "mean_signature_cosine": float(valid.mean()) if len(valid) else np.nan,
                "std_signature_cosine": float(valid.std()) if len(valid) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_benchmark(perf: pd.DataFrame, stability: pd.DataFrame) -> pd.DataFrame:
    return (
        perf.groupby("model", as_index=False)
        .agg(
            auroc_mean=("auroc", "mean"),
            average_precision_mean=("average_precision", "mean"),
            precision_at_5pct_score_mean=("precision_at_5pct_score", "mean"),
            precision_at_5pct_explanation_rank_mean=("precision_at_5pct_explanation_rank", "mean"),
            n_seeds=("seed", "count"),
        )
        .merge(stability, on="model", how="left")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--seeds", default=None)
    parser.add_argument("--n-jobs", type=int, default=2)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument(
        "--stability-only-from",
        default=None,
        help="Reuse an existing run's raw and feature-signature CSV files and recompute only stability summaries.",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else base_dir / "results" / "second_transfer_benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.stability_only_from:
        source_dir = Path(args.stability_only_from).resolve()
        perf = pd.read_csv(source_dir / "second_transfer_raw.csv")
        sig_df = pd.read_csv(source_dir / "feature_signature_audit.csv")
        stability = summarize_signature_stability(sig_df)
        benchmark = build_benchmark(perf, stability)
        perf.to_csv(out_dir / "second_transfer_raw.csv", index=False)
        sig_df.to_csv(out_dir / "feature_signature_audit.csv", index=False)
        stability.to_csv(out_dir / "signature_stability.csv", index=False)
        benchmark.to_csv(out_dir / "benchmark_results.csv", index=False)
        write_json(
            out_dir / "second_transfer_summary.json",
            {
                "run_completed_utc": utc_now(),
                "mode": "stability_only_recompute",
                "source_dir": str(source_dir),
                "models": sorted(sig_df["model"].unique()),
                "caveat": "KDDCup99 is a real network telemetry transfer check; claims should remain external-validation scoped.",
            },
        )
        print(f"STABILITY_ONLY_OK {out_dir}")
        return
    timing = TimingLog(out_dir / "timings.jsonl")
    write_json(out_dir / "resource_report_start.json", resource_snapshot())

    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else ([0] if args.smoke else [0, 1, 2, 3, 4])
    max_rows = args.max_rows if args.max_rows is not None else (2500 if args.smoke else 50_000)
    model_names = ["logistic", "isolation_forest"] if args.smoke else ["logistic", "random_forest", "hgb", "isolation_forest"]
    rows = []
    signature_rows = []
    stability_vectors: dict[str, list[np.ndarray]] = {m: [] for m in model_names}

    with timing.stage("load_kddcup99", max_rows=max_rows):
        x_all, y_all = load_kdd(seeds[0], max_rows)
        features, numeric, categorical = split_columns(x_all)
    write_json(
        out_dir / "second_transfer_manifest.json",
        {
            "run_started_utc": utc_now(),
            "dataset": "sklearn.fetch_kddcup99 subset=SA percent10=True",
            "positioning": "Second real telemetry-like transfer benchmark, not direct satellite validation.",
            "smoke": args.smoke,
            "max_rows": max_rows,
            "models": model_names,
            "features": features,
            "numeric_features": numeric,
            "categorical_features": categorical,
            "thread_env": {k: os.environ.get(k) for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]},
        },
    )

    sig_sample_n = min(len(x_all), 250 if args.smoke else 1200)
    for seed in seeds:
        x_train, x_test, y_train, y_test = train_test_split(
            x_all, y_all, test_size=0.35, random_state=seed, stratify=y_all
        )
        pre = make_preprocessor(numeric, categorical)
        for model_name in model_names:
            supervised = model_name in {"logistic", "random_forest", "hgb"}
            if model_name == "logistic":
                clf = LogisticRegression(max_iter=500, class_weight="balanced", random_state=seed)
                model = Pipeline([("pre", pre), ("clf", clf)])
            elif model_name == "random_forest":
                clf = RandomForestClassifier(
                    n_estimators=220,
                    min_samples_leaf=3,
                    class_weight="balanced_subsample",
                    n_jobs=args.n_jobs,
                    random_state=seed,
                )
                model = Pipeline([("pre", pre), ("clf", clf)])
            elif model_name == "hgb":
                clf = HistGradientBoostingClassifier(max_iter=180, learning_rate=0.05, random_state=seed)
                model = Pipeline([("pre", pre), ("clf", clf)])
            elif model_name == "isolation_forest":
                model = Pipeline(
                    [
                        ("pre", pre),
                        (
                            "det",
                            IsolationForest(
                                n_estimators=220,
                                contamination=max(0.01, min(0.45, float(np.mean(y_train)))),
                                random_state=seed,
                                n_jobs=args.n_jobs,
                            ),
                        ),
                    ]
                )
            else:
                raise ValueError(model_name)

            train_x = x_train if supervised else x_train.iloc[y_train == 0]
            train_y = y_train if supervised else None
            with timing.stage("train", seed=seed, model=model_name):
                if train_y is None:
                    model.fit(train_x)
                else:
                    model.fit(train_x, train_y)
            with timing.stage("score", seed=seed, model=model_name):
                score = normalize_score(model_score(model, x_test))
            rng = np.random.default_rng(seed)
            idx = rng.choice(len(x_test), size=sig_sample_n, replace=False)
            with timing.stage("feature_signature", seed=seed, model=model_name):
                sig = signature_vector(model, x_test.iloc[idx].reset_index(drop=True), y_test[idx], features, seed, supervised)
            sig["seed"] = seed
            sig["model"] = model_name
            signature_rows.extend(sig.to_dict("records"))
            vec = sig.set_index("feature")["importance"].reindex(features).fillna(0.0).to_numpy()
            stability_vectors[model_name].append(vec)
            concentration = explanation_concentration(x_test, numeric, x_train, sig)
            hybrid_score = score * (1.0 + concentration)
            rows.append(
                {
                    "seed": seed,
                    "model": model_name,
                    "auroc": float(roc_auc_score(y_test, score)),
                    "average_precision": float(average_precision_score(y_test, score)),
                    "precision_at_1pct_score": precision_at_fraction(y_test, score, 0.01),
                    "precision_at_5pct_score": precision_at_fraction(y_test, score, 0.05),
                    "precision_at_1pct_explanation_rank": precision_at_fraction(y_test, hybrid_score, 0.01),
                    "precision_at_5pct_explanation_rank": precision_at_fraction(y_test, hybrid_score, 0.05),
                    "alert_precision_default": float(precision_score(y_test, score >= 0.5, zero_division=0)),
                    "mean_explanation_concentration": float(np.mean(concentration)),
                }
            )

    perf = pd.DataFrame(rows)
    sig_df = pd.DataFrame(signature_rows)
    stability = summarize_signature_stability(sig_df)
    benchmark = build_benchmark(perf, stability)
    perf.to_csv(out_dir / "second_transfer_raw.csv", index=False)
    benchmark.to_csv(out_dir / "benchmark_results.csv", index=False)
    sig_df.sort_values(["model", "seed", "importance"], ascending=[True, True, False]).to_csv(
        out_dir / "feature_signature_audit.csv", index=False
    )
    stability.to_csv(out_dir / "signature_stability.csv", index=False)
    pd.read_json(out_dir / "timings.jsonl", lines=True).groupby("stage", as_index=False)["wall_seconds"].sum().to_csv(
        out_dir / "runtime_by_stage.csv", index=False
    )
    write_json(
        out_dir / "second_transfer_summary.json",
        {
            "run_completed_utc": utc_now(),
            "n_rows": int(len(x_all)),
            "models": model_names,
            "caveat": "KDDCup99 is a real network telemetry transfer check; claims should remain external-validation scoped.",
        },
    )
    write_json(out_dir / "resource_report_end.json", resource_snapshot())


if __name__ == "__main__":
    main()

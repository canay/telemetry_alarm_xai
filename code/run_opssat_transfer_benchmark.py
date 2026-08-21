"""Bounded OPS-SAT diagnostic transfer check.

This script uses the small, extracted-feature OPSSAT-AD `dataset.csv` file
from Zenodo. It is a real spacecraft-telemetry detection/stability check, not
an injected-channel attribution-correctness benchmark.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


DATA_URL = "https://zenodo.org/records/12588359/files/dataset.csv?download=1"
DATA_DOI = "10.5281/zenodo.12588359"
MODELS = ("logistic", "random_forest", "hgb", "isolation_forest")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def one_hot_encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    den = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / den) if den else float("nan")


def summarize_signature_stability(sig_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model_name, group in sig_df.groupby("model"):
        wide = []
        for seed, seed_group in group.groupby("seed"):
            vec = seed_group.groupby("feature")["importance"].sum()
            wide.append((seed, vec))
        sims = []
        for i in range(len(wide)):
            for j in range(i + 1, len(wide)):
                idx = wide[i][1].index.union(wide[j][1].index)
                sims.append(
                    cosine(
                        wide[i][1].reindex(idx, fill_value=0).to_numpy(),
                        wide[j][1].reindex(idx, fill_value=0).to_numpy(),
                    )
                )
        valid = np.asarray([value for value in sims if np.isfinite(value)], dtype=float)
        rows.append(
            {
                "model": model_name,
                "n_pairs": int(len(valid)),
                "n_pairs_total": int(len(sims)),
                "n_pairs_valid": int(len(valid)),
                "n_pairs_degenerate": int(len(sims) - len(valid)),
                "mean_signature_cosine": float(valid.mean()) if len(valid) else np.nan,
                "std_signature_cosine": float(valid.std(ddof=0)) if len(valid) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def precision_at_fraction(y: np.ndarray, score: np.ndarray, frac: float = 0.05) -> float:
    k = max(1, int(math.ceil(len(y) * frac)))
    idx = np.argsort(-score)[:k]
    return float(np.mean(y[idx]))


def make_preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    return ColumnTransformer(
        [("num", StandardScaler(), numeric), ("cat", one_hot_encoder(), categorical)],
        sparse_threshold=0.0,
    )


def feature_names(pre: ColumnTransformer, numeric: list[str], categorical: list[str]) -> list[str]:
    names = list(numeric)
    enc = pre.named_transformers_["cat"]
    try:
        cat_names = enc.get_feature_names_out(categorical).tolist()
    except AttributeError:
        cat_names = enc.get_feature_names(categorical).tolist()
    return names + cat_names


def model_score(pipe: Pipeline, x: pd.DataFrame, supervised: bool) -> np.ndarray:
    if supervised:
        return pipe.predict_proba(x)[:, 1]
    return -pipe.named_steps["model"].score_samples(pipe.named_steps["pre"].transform(x))


def normalize(v: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(v)), float(np.max(v))
    return (v - lo) / (hi - lo + 1e-12)


def intrinsic_signature(pipe: Pipeline, model_name: str, names: list[str]) -> pd.DataFrame | None:
    model = pipe.named_steps["model"]
    if model_name == "logistic":
        imp = np.abs(model.coef_[0])
    elif model_name == "random_forest":
        imp = model.feature_importances_
    else:
        return None
    imp = imp / (imp.sum() + 1e-12)
    return pd.DataFrame({"feature": names, "importance": imp})


def perturbation_signature(
    pipe: Pipeline,
    x_test: pd.DataFrame,
    score: np.ndarray,
    features: list[str],
    supervised: bool,
    seed: int,
    max_rows: int,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 707)
    if len(x_test) > max_rows:
        idx = rng.choice(len(x_test), max_rows, replace=False)
        x_base = x_test.iloc[idx].reset_index(drop=True)
        base = score[idx]
    else:
        x_base = x_test.reset_index(drop=True)
        base = score
    rows = []
    for col in features:
        xp = x_base.copy()
        xp[col] = rng.permutation(xp[col].to_numpy())
        sp = model_score(pipe, xp, supervised)
        rows.append({"feature": col, "importance": float(np.mean(np.abs(base - sp)))})
    out = pd.DataFrame(rows)
    out["importance"] = out["importance"] / (out["importance"].sum() + 1e-12)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--data-path", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--seeds", default="0,1,2,3,4")
    parser.add_argument("--n-jobs", type=int, default=2)
    parser.add_argument("--max-signature-rows", type=int, default=529)
    args = parser.parse_args()

    t0 = time.time()
    base = Path(args.base_dir).resolve()
    data_path = Path(args.data_path).resolve() if args.data_path else base / "data" / "external" / "opssat" / "dataset.csv"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else base / "results" / "opssat_transfer_benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(data_path)
    y = df["anomaly"].astype(int).to_numpy()
    train_mask = df["train"].astype(int).to_numpy() == 1
    test_mask = ~train_mask

    drop_cols = {"segment", "anomaly", "train"}
    categorical = [c for c in ["channel", "sampling"] if c in df.columns]
    features = [c for c in df.columns if c not in drop_cols]
    numeric = [c for c in features if c not in categorical]
    x = df[features]
    x_train, x_test = x.loc[train_mask].reset_index(drop=True), x.loc[test_mask].reset_index(drop=True)
    y_train, y_test = y[train_mask], y[test_mask]

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    perf_rows: list[dict] = []
    sig_rows: list[dict] = []

    for seed in seeds:
        rng = np.random.default_rng(seed)
        boot = rng.choice(len(x_train), len(x_train), replace=True)
        x_boot = x_train.iloc[boot].reset_index(drop=True)
        y_boot = y_train[boot]
        normal_boot = y_boot == 0

        for model_name in MODELS:
            supervised = model_name != "isolation_forest"
            if model_name == "logistic":
                model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed)
            elif model_name == "random_forest":
                model = RandomForestClassifier(
                    n_estimators=300,
                    class_weight="balanced",
                    max_features="sqrt",
                    random_state=seed,
                    n_jobs=args.n_jobs,
                )
            elif model_name == "hgb":
                model = HistGradientBoostingClassifier(max_iter=180, learning_rate=0.05, random_state=seed)
            else:
                contamination = max(0.01, min(0.45, float(np.mean(y_boot))))
                model = IsolationForest(n_estimators=300, contamination=contamination, random_state=seed, n_jobs=args.n_jobs)

            pipe = Pipeline([("pre", make_preprocessor(numeric, categorical)), ("model", model)])
            fit_x = x_boot if supervised else x_boot.loc[normal_boot].reset_index(drop=True)
            fit_y = y_boot if supervised else None
            if fit_y is None:
                pipe.fit(fit_x)
            else:
                pipe.fit(fit_x, fit_y)
            raw_score = model_score(pipe, x_test, supervised)
            score = normalize(raw_score)
            names = feature_names(pipe.named_steps["pre"], numeric, categorical)
            sig = intrinsic_signature(pipe, model_name, names)
            if sig is None:
                sig = perturbation_signature(
                    pipe,
                    x_test,
                    raw_score,
                    features,
                    supervised,
                    seed,
                    args.max_signature_rows,
                )
            sig["seed"] = seed
            sig["model"] = model_name
            sig_rows.extend(sig.to_dict("records"))
            perf_rows.append(
                {
                    "seed": seed,
                    "model": model_name,
                    "auroc": float(roc_auc_score(y_test, score)),
                    "ap": float(average_precision_score(y_test, score)),
                    "p_at_5pct": precision_at_fraction(y_test, score, 0.05),
                    "n_train": int(len(y_train)),
                    "n_test": int(len(y_test)),
                    "n_test_anomaly": int(y_test.sum()),
                }
            )

    perf = pd.DataFrame(perf_rows)
    sig_df = pd.DataFrame(sig_rows)
    sig_df.to_csv(out_dir / "feature_signature_audit.csv", index=False)
    perf.to_csv(out_dir / "opssat_raw.csv", index=False)

    stability = summarize_signature_stability(sig_df)
    stability.to_csv(out_dir / "signature_stability.csv", index=False)

    summary = (
        perf.groupby("model")
        .agg(
            auroc_mean=("auroc", "mean"),
            auroc_std=("auroc", "std"),
            ap_mean=("ap", "mean"),
            ap_std=("ap", "std"),
            p_at_5pct_mean=("p_at_5pct", "mean"),
            p_at_5pct_std=("p_at_5pct", "std"),
            n_seeds=("seed", "count"),
        )
        .reset_index()
        .merge(stability, on="model", how="left")
    )
    summary.to_csv(out_dir / "benchmark_results.csv", index=False)
    write_json(
        out_dir / "opssat_manifest.json",
        {
            "dataset": "OPSSAT-AD Zenodo dataset.csv extracted-feature table",
            "dataset_url": DATA_URL,
            "dataset_doi": DATA_DOI,
            "positioning": "Real OPS-SAT telemetry diagnostic transfer check for detection and feature-signature stability; not fault-channel attribution correctness.",
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "train_rows": int(train_mask.sum()),
            "test_rows": int(test_mask.sum()),
            "test_anomalies": int(y_test.sum()),
            "models": list(MODELS),
            "seeds": seeds,
            "runtime_s": time.time() - t0,
            "python": platform.python_version(),
            "thread_policy": {"n_jobs": args.n_jobs},
        },
    )
    print("OPSSAT_OK", out_dir)


if __name__ == "__main__":
    main()

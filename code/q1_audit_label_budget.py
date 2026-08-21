"""Supervised label-budget sensitivity for the Q1 audit revision.

The main benchmark gives supervised baselines access to all labeled windows.
This script refits the supervised detectors on stratified fractions of the
labeled window pool and evaluates each refit on the same held-out test split.
It reuses the existing feature checkpoints and does not regenerate telemetry.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import event_metrics  # noqa: E402
import models as M  # noqa: E402


SUPERVISED_MODELS = ["lr", "dtree", "hgb"]
LABEL_FRACTIONS = [0.10, 0.25, 0.50, 1.00]
N_REP = 3


def _load_seed(base: Path, seed: int) -> tuple[np.lib.npyio.NpzFile, list[dict]]:
    feat = np.load(base / "ckpt" / f"feat_seed{seed}.npz")
    raw = np.load(base / "data" / f"telemetry_seed{seed}.npz")
    events = json.loads(str(raw["ev_te"]))
    return feat, events


def _stratified_subset(y: np.ndarray, fraction: float, rng: np.random.Generator) -> np.ndarray:
    if fraction >= 0.999:
        return np.arange(len(y))
    chosen = []
    for cls in (0, 1):
        idx = np.where(y == cls)[0]
        n_take = max(1, int(round(fraction * len(idx))))
        chosen.append(rng.choice(idx, size=n_take, replace=False))
    out = np.concatenate(chosen)
    rng.shuffle(out)
    return out


def _fit_and_score(
    model_name: str,
    seed: int,
    fraction: float,
    Ztr: np.ndarray,
    Zval: np.ndarray,
    Ztl: np.ndarray,
    ytl: np.ndarray,
    Zte: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    rng = np.random.default_rng(20260627 + seed * 1009 + int(round(fraction * 1000)))
    subset = _stratified_subset(ytl, fraction, rng)
    Ztl_sub = Ztl[subset]
    ytl_sub = ytl[subset]
    sc_te = []
    sc_val = []
    for rep in range(N_REP):
        model = M.fit_model(model_name, 100 * seed + rep, Ztr, Ztl_sub, ytl_sub)
        sc_te.append(M.score(model_name, model, Zte))
        sc_val.append(M.score(model_name, model, Zval))
    return (
        np.mean(np.asarray(sc_te), axis=0),
        np.mean(np.asarray(sc_val), axis=0),
        int(ytl_sub.sum()),
        int((ytl_sub == 0).sum()),
    )


def main() -> None:
    base = Path(__file__).resolve().parents[1]
    out_dir = base / "results" / "q1_audit_revision"
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_rows = []
    for seed in range(5):
        feat, events = _load_seed(base, seed)
        Ztr = feat["Xtr_F"]
        Zval = feat["Xval_F"]
        Ztl = feat["Xtl_F"]
        Zte = feat["Xte_F"]
        ytl = feat["ytl_w"]
        yte = feat["yte_w"]
        starts_te = feat["Xte_S"]
        for model_name in SUPERVISED_MODELS:
            for fraction in LABEL_FRACTIONS:
                ms_te, ms_val, label_pos, label_neg = _fit_and_score(
                    model_name, seed, fraction, Ztr, Zval, Ztl, ytl, Zte
                )
                threshold = float(np.quantile(ms_val, 0.99))
                em = event_metrics(ms_te, threshold, starts_te, events, len(starts_te))
                seed_rows.append(
                    {
                        "model": model_name,
                        "seed": seed,
                        "label_fraction": fraction,
                        "label_pos": label_pos,
                        "label_neg": label_neg,
                        "auroc": float(roc_auc_score(yte, ms_te)),
                        "ap": float(average_precision_score(yte, ms_te)),
                        "prec_ev": em["prec_ev"],
                        "rec_ev": em["rec_ev"],
                        "f1_ev": em["f1_ev"],
                        "f1_pa": em["f1_pa"],
                        "n_episodes": em["n_episodes"],
                    }
                )

    seed_path = out_dir / "label_budget_sensitivity_seed.csv"
    with seed_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(seed_rows[0].keys()))
        writer.writeheader()
        writer.writerows(seed_rows)

    summary_rows = []
    for model_name in SUPERVISED_MODELS:
        full_rows = [
            row
            for row in seed_rows
            if row["model"] == model_name and float(row["label_fraction"]) == 1.00
        ]
        full_by_seed = {int(row["seed"]): row for row in full_rows}
        for fraction in LABEL_FRACTIONS:
            selected = [
                row
                for row in seed_rows
                if row["model"] == model_name and float(row["label_fraction"]) == fraction
            ]
            f1 = np.asarray([row["f1_ev"] for row in selected], dtype=float)
            auroc = np.asarray([row["auroc"] for row in selected], dtype=float)
            ap = np.asarray([row["ap"] for row in selected], dtype=float)
            prec = np.asarray([row["prec_ev"] for row in selected], dtype=float)
            rec = np.asarray([row["rec_ev"] for row in selected], dtype=float)
            f1_delta = np.asarray(
                [row["f1_ev"] - full_by_seed[int(row["seed"])]["f1_ev"] for row in selected],
                dtype=float,
            )
            auroc_delta = np.asarray(
                [row["auroc"] - full_by_seed[int(row["seed"])]["auroc"] for row in selected],
                dtype=float,
            )
            ap_delta = np.asarray(
                [row["ap"] - full_by_seed[int(row["seed"])]["ap"] for row in selected],
                dtype=float,
            )
            summary_rows.append(
                {
                    "model": model_name,
                    "label_fraction": fraction,
                    "label_pos_mean": float(np.mean([row["label_pos"] for row in selected])),
                    "label_neg_mean": float(np.mean([row["label_neg"] for row in selected])),
                    "auroc_mean": float(auroc.mean()),
                    "auroc_sd": float(auroc.std(ddof=1)),
                    "auroc_delta_vs_full_mean": float(auroc_delta.mean()),
                    "ap_mean": float(ap.mean()),
                    "ap_sd": float(ap.std(ddof=1)),
                    "ap_delta_vs_full_mean": float(ap_delta.mean()),
                    "prec_ev_mean": float(prec.mean()),
                    "rec_ev_mean": float(rec.mean()),
                    "f1_ev_mean": float(f1.mean()),
                    "f1_ev_sd": float(f1.std(ddof=1)),
                    "f1_delta_vs_full_mean": float(f1_delta.mean()),
                    "n_episodes_mean": float(np.mean([row["n_episodes"] for row in selected])),
                    "n_seeds": len(selected),
                }
            )

    summary_path = out_dir / "label_budget_sensitivity.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    print("LABEL_BUDGET_OK", seed_path, summary_path)


if __name__ == "__main__":
    main()

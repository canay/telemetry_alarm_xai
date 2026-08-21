"""Supplemental statistics for the Q1 audit revision.

Computes detector-stratified bootstrap intervals, priority sensitivity
summaries, and compact statistical-test records from the existing synthetic
result artifacts. The script does not refit models.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy import stats

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import event_metrics, ndcg_at_k, windows_of_event  # noqa: E402


MODELS = ["lr", "dtree", "iforest", "hgb", "pca", "ae"]


def parse_seed_spec(spec: str) -> list[int]:
    seeds: list[int] = []
    for chunk in spec.split(","):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start = int(left)
            stop = int(right)
            step = 1 if stop >= start else -1
            seeds.extend(range(start, stop + step, step))
        else:
            seeds.append(int(part))
    if not seeds:
        raise argparse.ArgumentTypeError("seed specification is empty")
    return list(dict.fromkeys(seeds))


def bootstrap_ci(values: np.ndarray, rng: np.random.Generator, n_boot: int = 10000) -> tuple[float, float]:
    samples = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(values), len(values))
        samples.append(float(np.mean(values[idx])))
    return float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


def bh_adjust(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted q-values, preserving input order."""
    if not pvals:
        return []
    arr = np.asarray(pvals, dtype=float)
    order = np.argsort(arr)
    qvals = np.empty(len(arr), dtype=float)
    running = 1.0
    for rank, idx in reversed(list(enumerate(order, start=1))):
        running = min(running, arr[idx] * len(arr) / rank)
        qvals[idx] = running
    return [float(q) for q in qvals]


def _safe_wilcoxon(values: np.ndarray) -> tuple[float, float]:
    if len(values) == 0:
        return float("nan"), float("nan")
    if np.allclose(values, 0.0):
        return 0.0, 1.0
    w = stats.wilcoxon(values)
    return float(w.statistic), float(w.pvalue)


def _z(values: np.ndarray) -> np.ndarray:
    return (values - values.mean()) / (values.std() + 1e-12)


def _priority_keys(sc: np.ndarray, st: np.ndarray, co: np.ndarray) -> dict[str, np.ndarray]:
    zsc = _z(sc)
    zst = _z(st)
    zco = _z(co)
    evidence = zst + zco
    top_k = min(10, len(zsc))
    cutoff = np.sort(zsc)[-top_k] if top_k else 0.0
    dist = np.abs(zsc - cutoff)
    soft_gate = 1.0 / (1.0 + np.exp((dist - 0.75) / 0.25))
    return {
        "score_only": sc,
        "additive_full": zsc + evidence,
        "multiplicative_stability": (sc - sc.min() + 1e-6) * (0.5 + st),
        "score_dominant_025": zsc + 0.25 * evidence,
        "score_dominant_050": zsc + 0.50 * evidence,
        "cutoff_gate_05": zsc + (dist <= 0.5).astype(float) * evidence,
        "cutoff_gate_10": zsc + (dist <= 1.0).astype(float) * evidence,
        "soft_cutoff_gate": zsc + soft_gate * evidence,
        "stability_positive_gate": zsc + (zst > 0.0).astype(float) * evidence,
    }


def _rank_metrics_from_episode_rows(ep_rows: list[dict], keyvals: np.ndarray) -> dict[str, float]:
    order = np.argsort(-np.asarray(keyvals))
    rels = [ep_rows[i]["rel"] for i in order]
    return {
        "ndcg10": float(ndcg_at_k(rels, 10)),
        "p5_hisev": float(np.mean([r == 3 for r in rels[:5]])) if rels else 0.0,
    }


def _overlapping_event_ids(episode: tuple[int, int], starts: np.ndarray, events: list[dict]) -> list[int]:
    a, b = episode
    ids = []
    ep_windows = set(range(a, b + 1))
    for event_idx, event in enumerate(events):
        wi = windows_of_event(starts, event)
        if len(ep_windows & set(wi.tolist())):
            ids.append(event_idx)
    return ids


def _dedup_ndcg(ep_rows: list[dict], keyvals: np.ndarray, event_ids: list[list[int]], events: list[dict]) -> float:
    """Event-deduplicated diagnostic NDCG.

    The first ranked alarm episode that overlaps an event receives that event's
    severity. Later episodes overlapping only already-claimed events receive
    zero gain. This is a sensitivity diagnostic, not the metric used in the
    original experiments.
    """
    seen: set[int] = set()
    rels = []
    for ep_idx in np.argsort(-np.asarray(keyvals)):
        candidates = [idx for idx in event_ids[ep_idx] if idx not in seen]
        if not candidates:
            rels.append(0)
            continue
        chosen = max(candidates, key=lambda idx: events[idx]["sev"])
        seen.add(chosen)
        rels.append(events[chosen]["sev"])
    return float(ndcg_at_k(rels, 10))


def _episode_event_ids(base: Path, seed: int, model: str) -> tuple[list[list[int]], list[dict]]:
    ckpt = base / "ckpt"
    data = base / "data"
    payload = json.loads((base / "results" / "raw" / f"model_seed{seed}_{model}.json").read_text(encoding="utf-8"))
    feat = np.load(ckpt / f"feat_seed{seed}.npz")
    model_npz = np.load(ckpt / f"model_seed{seed}_{model}.npz")
    d = np.load(data / f"telemetry_seed{seed}.npz")
    events = json.loads(str(d["ev_te"]))
    starts = feat["Xte_S"]
    em = event_metrics(model_npz["ms_te"], float(model_npz["thr"]), starts, events, len(starts))
    if len(em["episodes"]) != len(payload["episodes"]):
        raise RuntimeError(f"episode mismatch seed={seed} model={model}")
    ids = [_overlapping_event_ids(ep, starts, events) for ep in em["episodes"]]
    return ids, events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="0-4", help="Seed list/range, for example 0-4 or 0-9.")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Relative paths are resolved from the project root.",
    )
    args = parser.parse_args()
    seeds = parse_seed_spec(args.seeds)
    base = Path(__file__).resolve().parents[1]
    raw = base / "results" / "raw"
    out_dir = Path(args.out_dir) if args.out_dir else base / "results" / "q1_audit_revision"
    if not out_dir.is_absolute():
        out_dir = base / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260624)

    rows = []
    sensitivity_rows = []
    seed_gain_rows = []
    ablation_seed_rows = []
    adaptive_seed_rows = []
    f1_by_model = {model: [] for model in MODELS}
    for model in MODELS:
        ndcg_gains = []
        p5_gains = []
        add_minus_mult = []
        dedup_base = []
        dedup_add = []
        dedup_mult = []
        for seed in seeds:
            payload = json.loads((raw / f"model_seed{seed}_{model}.json").read_text(encoding="utf-8"))
            f1_by_model[model].append(payload["f1_ev"])
            ep_rows = payload["episodes"]
            sc = np.array([r["score"] for r in ep_rows], dtype=float)
            st = np.array([r["stab"] for r in ep_rows], dtype=float)
            co = np.array([r["conc"] for r in ep_rows], dtype=float)
            priority_keys = _priority_keys(sc, st, co)
            add_key = priority_keys["additive_full"]
            mult_key = priority_keys["multiplicative_stability"]
            ablation_keys = {
                "score_only": sc,
                "stability_only": st,
                "concentration_only": co,
                "score_plus_stability": _z(sc) + _z(st),
                "score_plus_concentration": _z(sc) + _z(co),
                "evidence_only": _z(st) + _z(co),
                "additive_full": add_key,
                "multiplicative_stability": mult_key,
            }
            ablation_metrics = {
                variant: _rank_metrics_from_episode_rows(ep_rows, values)
                for variant, values in ablation_keys.items()
            }
            ndcg_gain = ablation_metrics["additive_full"]["ndcg10"] - ablation_metrics["score_only"]["ndcg10"]
            p5_gain = ablation_metrics["additive_full"]["p5_hisev"] - ablation_metrics["score_only"]["p5_hisev"]
            ndcg_gains.append(ndcg_gain)
            p5_gains.append(p5_gain)
            add_minus_mult.append(
                ablation_metrics["additive_full"]["ndcg10"]
                - ablation_metrics["multiplicative_stability"]["ndcg10"]
            )
            score_ndcg = ablation_metrics["score_only"]["ndcg10"]
            score_p5 = ablation_metrics["score_only"]["p5_hisev"]
            for variant, metrics in ablation_metrics.items():
                ablation_seed_rows.append(
                    {
                        "model": model,
                        "seed": seed,
                        "variant": variant,
                        "ndcg10": metrics["ndcg10"],
                        "p5_hisev": metrics["p5_hisev"],
                        "ndcg_gain_vs_score": metrics["ndcg10"] - score_ndcg,
                        "p5_gain_vs_score": metrics["p5_hisev"] - score_p5,
                    }
                )
            adaptive_metrics = {
                variant: _rank_metrics_from_episode_rows(ep_rows, values)
                for variant, values in priority_keys.items()
            }
            for variant, metrics in adaptive_metrics.items():
                adaptive_seed_rows.append(
                    {
                        "model": model,
                        "seed": seed,
                        "variant": variant,
                        "ndcg10": metrics["ndcg10"],
                        "p5_hisev": metrics["p5_hisev"],
                        "ndcg_gain_vs_score": metrics["ndcg10"] - score_ndcg,
                        "p5_gain_vs_score": metrics["p5_hisev"] - score_p5,
                    }
                )
            event_ids, events = _episode_event_ids(base, seed, model)
            dedup_base.append(_dedup_ndcg(ep_rows, sc, event_ids, events))
            dedup_add.append(_dedup_ndcg(ep_rows, add_key, event_ids, events))
            dedup_mult.append(_dedup_ndcg(ep_rows, mult_key, event_ids, events))
            seed_gain_rows.append(
                {
                    "model": model,
                    "seed": seed,
                    "ndcg_gain_add": ndcg_gain,
                    "p5_gain_add": p5_gain,
                    "ndcg_gain_add_minus_mult": ablation_metrics["additive_full"]["ndcg10"]
                    - ablation_metrics["multiplicative_stability"]["ndcg10"],
                    "dedup_gain_add": dedup_add[-1] - dedup_base[-1],
                    "dedup_gain_mult": dedup_mult[-1] - dedup_base[-1],
                }
            )
        ndcg = np.asarray(ndcg_gains, dtype=float)
        p5 = np.asarray(p5_gains, dtype=float)
        ndcg_lo, ndcg_hi = bootstrap_ci(ndcg, rng)
        p5_lo, p5_hi = bootstrap_ci(p5, rng)
        rows.append(
            {
                "model": model,
                "ndcg_gain_mean": float(ndcg.mean()),
                "ndcg_ci_low": ndcg_lo,
                "ndcg_ci_high": ndcg_hi,
                "p5_gain_mean": float(p5.mean()),
                "p5_ci_low": p5_lo,
                "p5_ci_high": p5_hi,
                "n_seeds": len(seeds),
            }
        )
        sensitivity_rows.append(
            {
                "model": model,
                "baseline_ndcg": float(np.mean([row["ndcg10"] for row in ablation_seed_rows if row["model"] == model and row["variant"] == "score_only"])),
                "add_ndcg": float(np.mean([row["ndcg10"] for row in ablation_seed_rows if row["model"] == model and row["variant"] == "additive_full"])),
                "mult_ndcg": float(np.mean([row["ndcg10"] for row in ablation_seed_rows if row["model"] == model and row["variant"] == "multiplicative_stability"])),
                "add_gain": float(ndcg.mean()),
                "mult_gain": float(np.mean([
                    row["ndcg_gain_vs_score"]
                    for row in ablation_seed_rows
                    if row["model"] == model and row["variant"] == "multiplicative_stability"
                ])),
                "dedup_baseline_ndcg": float(np.mean(dedup_base)),
                "dedup_add_ndcg": float(np.mean(dedup_add)),
                "dedup_mult_ndcg": float(np.mean(dedup_mult)),
                "dedup_add_gain": float(np.mean(np.asarray(dedup_add) - np.asarray(dedup_base))),
                "dedup_mult_gain": float(np.mean(np.asarray(dedup_mult) - np.asarray(dedup_base))),
                "add_minus_mult_ndcg": float(np.mean(add_minus_mult)),
                "n_seeds": len(seeds),
            }
        )

    csv_path = out_dir / "priority_gain_bootstrap_ci.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "priority_gain_bootstrap_ci.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    sens_path = out_dir / "priority_sensitivity.csv"
    with sens_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(sensitivity_rows[0].keys()))
        writer.writeheader()
        writer.writerows(sensitivity_rows)
    ablation_seed_path = out_dir / "priority_ablation_seed.csv"
    with ablation_seed_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ablation_seed_rows[0].keys()))
        writer.writeheader()
        writer.writerows(ablation_seed_rows)
    ablation_rows = []
    variants = list(dict.fromkeys(row["variant"] for row in ablation_seed_rows))
    for model in MODELS:
        for variant in variants:
            selected = [row for row in ablation_seed_rows if row["model"] == model and row["variant"] == variant]
            ndcg_vals = np.asarray([row["ndcg10"] for row in selected], dtype=float)
            p5_vals = np.asarray([row["p5_hisev"] for row in selected], dtype=float)
            gain_vals = np.asarray([row["ndcg_gain_vs_score"] for row in selected], dtype=float)
            p5_gain_vals = np.asarray([row["p5_gain_vs_score"] for row in selected], dtype=float)
            ablation_rows.append(
                {
                    "model": model,
                    "variant": variant,
                    "ndcg10_mean": float(ndcg_vals.mean()),
                    "ndcg10_sd": float(ndcg_vals.std(ddof=1)),
                    "ndcg_gain_vs_score_mean": float(gain_vals.mean()),
                    "p5_hisev_mean": float(p5_vals.mean()),
                    "p5_gain_vs_score_mean": float(p5_gain_vals.mean()),
                    "n_seeds": len(selected),
                }
            )
    ablation_path = out_dir / "priority_ablation.csv"
    with ablation_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ablation_rows[0].keys()))
        writer.writeheader()
        writer.writerows(ablation_rows)
    adaptive_seed_path = out_dir / "priority_adaptive_seed.csv"
    with adaptive_seed_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(adaptive_seed_rows[0].keys()))
        writer.writeheader()
        writer.writerows(adaptive_seed_rows)
    adaptive_rows = []
    adaptive_variants = list(dict.fromkeys(row["variant"] for row in adaptive_seed_rows))
    for scope in ["pooled", *MODELS]:
        for variant in adaptive_variants:
            selected = [
                row
                for row in adaptive_seed_rows
                if row["variant"] == variant and (scope == "pooled" or row["model"] == scope)
            ]
            ndcg_vals = np.asarray([row["ndcg10"] for row in selected], dtype=float)
            p5_vals = np.asarray([row["p5_hisev"] for row in selected], dtype=float)
            gain_vals = np.asarray([row["ndcg_gain_vs_score"] for row in selected], dtype=float)
            p5_gain_vals = np.asarray([row["p5_gain_vs_score"] for row in selected], dtype=float)
            adaptive_rows.append(
                {
                    "scope": scope,
                    "variant": variant,
                    "ndcg10_mean": float(ndcg_vals.mean()),
                    "ndcg10_sd": float(ndcg_vals.std(ddof=1)) if len(ndcg_vals) > 1 else 0.0,
                    "ndcg_gain_vs_score_mean": float(gain_vals.mean()),
                    "p5_hisev_mean": float(p5_vals.mean()),
                    "p5_gain_vs_score_mean": float(p5_gain_vals.mean()),
                    "n_blocks": len(selected),
                }
            )
    adaptive_path = out_dir / "priority_adaptive_summary.csv"
    with adaptive_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(adaptive_rows[0].keys()))
        writer.writeheader()
        writer.writerows(adaptive_rows)
    adaptive_test_rows = []
    adaptive_pvals = []
    for variant in [v for v in adaptive_variants if v != "score_only"]:
        for scope in MODELS:
            gains = np.asarray(
                [
                    row["ndcg_gain_vs_score"]
                    for row in adaptive_seed_rows
                    if row["variant"] == variant and row["model"] == scope
                ],
                dtype=float,
            )
            stat, p_value = _safe_wilcoxon(gains)
            adaptive_pvals.append(p_value)
            adaptive_test_rows.append(
                {
                    "test": f"priority_{variant}_ndcg_gain_wilcoxon_{scope}",
                    "test_family": "priority_adaptive_ndcg_gain",
                    "variant": variant,
                    "scope": scope,
                    "stat": stat,
                    "p": p_value,
                    "bh_q": 0.0,
                    "effect": float(gains.mean()),
                    "effect_label": "mean_gain",
                    "n_blocks": len(gains),
                }
            )
    for row, q in zip(adaptive_test_rows, bh_adjust(adaptive_pvals)):
        row["bh_q"] = float(q)
    adaptive_test_path = out_dir / "priority_adaptive_tests.csv"
    with adaptive_test_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(adaptive_test_rows[0].keys()))
        writer.writeheader()
        writer.writerows(adaptive_test_rows)
    (out_dir / "priority_seed_gains.csv").write_text(
        "\n".join(
            [",".join(seed_gain_rows[0].keys())]
            + [",".join(str(row[key]) for key in seed_gain_rows[0].keys()) for row in seed_gain_rows]
        )
        + "\n",
        encoding="utf-8",
    )

    f1_mat = np.array([[f1_by_model[model][idx] for model in MODELS] for idx, _seed in enumerate(seeds)])
    fr = stats.friedmanchisquare(*[f1_mat[:, j] for j in range(len(MODELS))])
    kendall_w = float(fr.statistic / (len(seeds) * (len(MODELS) - 1)))
    pair_rows = []
    pair_specs = [("ae", "lr"), ("ae", "hgb"), ("pca", "iforest")]
    pvals = []
    for a, b in pair_specs:
        av = np.asarray(f1_by_model[a], dtype=float)
        bv = np.asarray(f1_by_model[b], dtype=float)
        stat, p_value = _safe_wilcoxon(av - bv)
        pvals.append(p_value)
        diff = av - bv
        pair_rows.append(
            {
                "contrast": f"{a}_vs_{b}",
                "wilcoxon_stat": stat,
                "p": p_value,
                "mean_diff": float(diff.mean()),
                "median_diff": float(np.median(diff)),
            }
        )
    # Benjamini-Hochberg adjusted q-values for these pre-listed pair rows.
    for row, q in zip(pair_rows, bh_adjust(pvals)):
        row["bh_q"] = float(q)

    priority_rows = []
    priority_specs = []
    for model in MODELS:
        priority_specs.append(
            (
                model,
                [row["ndcg_gain_add"] for row in seed_gain_rows if row["model"] == model],
            )
        )
    priority_pvals = []
    for scope, values in priority_specs:
        values_arr = np.asarray(values, dtype=float)
        stat, p_value = _safe_wilcoxon(values_arr)
        priority_pvals.append(p_value)
        priority_rows.append(
            {
                "test": f"priority_additive_ndcg_gain_wilcoxon_{scope}",
                "test_family": "priority_ndcg_gain",
                "stat": stat,
                "p": p_value,
                "bh_q": 0.0,
                "effect": float(values_arr.mean()),
                "effect_label": "mean_gain",
                "n_blocks": len(values_arr),
            }
        )
    for row, q in zip(priority_rows, bh_adjust(priority_pvals)):
        row["bh_q"] = float(q)

    test_rows = [
        {
            "test": "friedman_event_f1",
            "test_family": "detector_f1_global",
            "stat": float(fr.statistic),
            "p": float(fr.pvalue),
            "bh_q": float(fr.pvalue),
            "effect": kendall_w,
            "effect_label": "kendall_w",
            "n_blocks": len(seeds),
        }
    ] + priority_rows
    test_path = out_dir / "statistical_tests.csv"
    with test_path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = list(test_rows[0].keys())
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(test_rows)

    pair_path = out_dir / "pairwise_tests.csv"
    with pair_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(pair_rows[0].keys()))
        writer.writeheader()
        writer.writerows(pair_rows)

    print(
        "Q1_STATS_OK",
        f"seeds={args.seeds}",
        csv_path,
        sens_path,
        ablation_path,
        adaptive_path,
        adaptive_test_path,
        test_path,
        pair_path,
    )


if __name__ == "__main__":
    main()

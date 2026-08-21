"""Aggregate all checkpoints into a provenance-preserving result summary."""
import argparse
import json, os, sys
from pathlib import Path
import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ndcg_at_k
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", default=os.path.join(BASE, "results", "results_summary.json"))
parser.add_argument("--versions-output", default=None)
args = parser.parse_args()
OUTPUT = Path(args.output).resolve()
VERSIONS_OUTPUT = (
    Path(args.versions_output).resolve()
    if args.versions_output
    else OUTPUT.with_name("versions.txt")
)
MODELS = ["lr", "dtree", "iforest", "hgb", "pca", "ae"]
FAMILY = {"lr": "interpretable", "dtree": "interpretable",
          "iforest": "tree-ensemble", "hgb": "tree-ensemble",
          "pca": "reconstruction", "ae": "reconstruction"}
TYPES = ["stuck", "dropout", "bias", "drift", "coupling", "runaway"]
SEEDS = range(5)

R = {m: [json.load(open(f"{BASE}/ckpt/model_seed{s}_{m}.json")) for s in SEEDS]
     for m in MODELS}
cross = [json.load(open(f"{BASE}/ckpt/cross_seed{s}.json")) for s in SEEDS]

def ms(v):
    values = np.asarray(v, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return dict(mean=float("nan"), std=float("nan"))
    return dict(
        mean=float(np.mean(values)),
        std=float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
    )

def rank_metrics(ep_rows, keyvals):
    order = np.argsort(-np.asarray(keyvals))
    rels = [ep_rows[i]["rel"] for i in order]
    return dict(ndcg10=float(ndcg_at_k(rels, 10)),
                p5_hisev=float(np.mean([r == 3 for r in rels[:5]])) if rels else 0.0)

def priority_metrics(row):
    ep_rows = row["episodes"]
    sc = np.array([e["score"] for e in ep_rows], dtype=float)
    st = np.array([e["stab"] for e in ep_rows], dtype=float)
    co = np.array([e["conc"] for e in ep_rows], dtype=float)
    z = lambda v: (v - v.mean()) / (v.std() + 1e-12)
    add = z(sc) + z(st) + z(co)
    mult = (sc - sc.min() + 1e-6) * (0.5 + st)
    return {
        "baseline": rank_metrics(ep_rows, sc),
        "aware_add": rank_metrics(ep_rows, add),
        "aware_mult": rank_metrics(ep_rows, mult),
    }

summary = {"models": {}, "per_type": {}, "attr": {}, "stability": {},
           "prio": {}, "cross_family": {}, "mode_robustness": {},
           "tests": {}, "openml": None, "meta": {}}

for m in MODELS:
    rows = R[m]
    summary["models"][m] = {
        "family": FAMILY[m],
        "auroc": ms([r["auroc"] for r in rows]),
        "ap": ms([r["ap"] for r in rows]),
        "prec_ev": ms([r["prec_ev"] for r in rows]),
        "rec_ev": ms([r["rec_ev"] for r in rows]),
        "f1_ev": ms([r["f1_ev"] for r in rows]),
        "f1_pa": ms([r["f1_pa"] for r in rows]),
        "n_detected": ms([r["n_detected"] for r in rows]),
        "n_episodes": ms([r["n_episodes"] for r in rows]),
        "runtime_s": ms([r["runtime"] for r in rows]),
    }
    summary["per_type"][m] = {
        t: {"auroc": ms([r["per_type"][t]["auroc"] for r in rows]),
            "rec_ev": ms([r["per_type"][t]["rec_ev"] for r in rows])}
        for t in TYPES}
    for meth in ["native", "occl"]:
        key = f"attr_{meth}"
        per_seed_h1 = [np.mean([e["hit1"] for e in r[key]]) if r[key] else np.nan for r in rows]
        per_seed_h3 = [np.mean([e["hit3"] for e in r[key]]) if r[key] else np.nan for r in rows]
        per_seed_rk = [np.mean([e["rank"] for e in r[key]]) if r[key] else np.nan for r in rows]
        summary["attr"].setdefault(m, {})[meth] = {
            "hit1": ms(per_seed_h1), "hit3": ms(per_seed_h3),
            "rank": ms(per_seed_rk),
            "per_type_hit3": {t: float(np.mean([e["hit3"] for r in rows
                              for e in r[key] if e["type"] == t] or [np.nan]))
                              for t in TYPES}}
    per_seed_j = [np.mean([e["jaccard"] for e in r["attr_native"]]) if r["attr_native"] else np.nan for r in rows]
    per_seed_s = [np.mean([e["spearman"] for e in r["attr_native"]]) if r["attr_native"] else np.nan for r in rows]
    summary["stability"][m] = {"jaccard3": ms(per_seed_j), "spearman": ms(per_seed_s)}
    # mode robustness (native attributions)
    mr = {}
    for mode in [0, 1]:
        h3 = [e["hit3"] for r in rows for e in r["attr_native"] if e["mode"] == mode]
        jc = [e["jaccard"] for r in rows for e in r["attr_native"] if e["mode"] == mode]
        mr[f"mode{mode}"] = {"hit3": float(np.mean(h3)), "jaccard3": float(np.mean(jc)),
                             "n": len(h3)}
    summary["mode_robustness"][m] = mr
    # prioritization
    pr = {}
    pr_rows = [priority_metrics(r) for r in rows]
    for variant in ["baseline", "aware_add", "aware_mult"]:
        pr[variant] = {
            "ndcg10": ms([r[variant]["ndcg10"] for r in pr_rows]),
            "p5_hisev": ms([r[variant]["p5_hisev"] for r in pr_rows])}
    pr["gain_add_ndcg"] = ms([r["aware_add"]["ndcg10"] -
                              r["baseline"]["ndcg10"] for r in pr_rows])
    pr["gain_add_p5"] = ms([r["aware_add"]["p5_hisev"] -
                            r["baseline"]["p5_hisev"] for r in pr_rows])
    summary["prio"][m] = pr

# cross-family attribution agreement
pair_acc = {}
for c in cross:
    for k, v in c["pairs"].items():
        if v is not None:
            pair_acc.setdefault(k, []).append(v["jaccard"])
summary["cross_family"] = {k: ms(v) for k, v in pair_acc.items()}

# statistical tests
f1_mat = np.array([[R[m][s]["f1_ev"] for m in MODELS] for s in SEEDS])
fr = stats.friedmanchisquare(*[f1_mat[:, j] for j in range(len(MODELS))])
summary["tests"]["friedman_f1"] = {"stat": float(fr.statistic), "p": float(fr.pvalue)}
# Wilcoxon: best recon (ae) vs best interpretable (lr), ae vs hgb
for a, b in [("ae", "lr"), ("ae", "hgb"), ("pca", "iforest")]:
    w = stats.wilcoxon([R[a][s]["f1_ev"] for s in SEEDS],
                       [R[b][s]["f1_ev"] for s in SEEDS])
    summary["tests"][f"wilcoxon_f1_{a}_vs_{b}"] = {"stat": float(w.statistic),
                                                   "p": float(w.pvalue)}
# Pooled model-seed gains are descriptive only because detector observations
# within a seed are not independent inferential blocks.
prio_by_model = {m: [priority_metrics(R[m][s]) for s in SEEDS] for m in MODELS}
gains = [prio_by_model[m][s]["aware_add"]["ndcg10"] -
         prio_by_model[m][s]["baseline"]["ndcg10"] for m in MODELS for s in SEEDS]
gains_p5 = [prio_by_model[m][s]["aware_add"]["p5_hisev"] -
            prio_by_model[m][s]["baseline"]["p5_hisev"] for m in MODELS for s in SEEDS]
summary["prio"]["pooled_descriptive"] = {
    "ndcg10_gain_mean": float(np.mean(gains)),
    "p5_hisev_gain_mean": float(np.mean(gains_p5)),
    "n_detector_seed_rows": len(gains),
    "n_independent_seeds": len(list(SEEDS)),
    "inference": "not_performed_due_to_within_seed_detector_dependence",
}

if os.path.exists(f"{BASE}/results/openml_results.json"):
    summary["openml"] = json.load(open(f"{BASE}/results/openml_results.json"))

import sklearn, scipy as sp, matplotlib, torch, shap, platform
summary["meta"] = dict(n_seeds=5, n_rep=3, window=20, stride=5,
                       n_channels=12, n_features=48,
                       events_per_seed=36, threshold_quantile=0.99)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with OUTPUT.open("w", encoding="utf-8") as f:
    json.dump(summary, f, indent=1)
VERSIONS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with VERSIONS_OUTPUT.open("w", encoding="utf-8") as f:
    f.write(f"python {platform.python_version()}\n")
    for mod in [np, sp, sklearn, matplotlib, torch, shap]:
        f.write(f"{mod.__name__} {mod.__version__}\n")
print(f"AGG_OK {OUTPUT}")

"""Publication figures. Usage: python3 figures.py <a|b|c|d|e|f> [...]"""
import argparse
import sys, os, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import windows_of_event, W, STRIDE
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("figures", nargs="+", choices=list("abcdef"))
parser.add_argument("--summary", default=os.path.join(BASE, "results", "results_summary.json"))
parser.add_argument("--out-dir", default=os.path.join(BASE, "figures"))
args = parser.parse_args()
FIG = os.path.abspath(args.out_dir)
os.makedirs(FIG, exist_ok=True)

plt.rcParams.update({
    "font.family": "Open Sans", "mathtext.fontset": "dejavusans",
    "font.size": 9, "axes.labelsize": 9, "legend.fontsize": 8,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.spines.top": False,
    "axes.spines.right": False, "figure.dpi": 600})

# Okabe-Ito colorblind-safe palette
OI = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9",
      "#F0E442", "#000000"]
MODELS = ["lr", "dtree", "iforest", "hgb", "pca", "ae"]
LBL = {"lr": "LR", "dtree": "DT", "iforest": "IF", "hgb": "HGB",
       "pca": "PCA", "ae": "AE"}
FAMC = {"lr": OI[0], "dtree": OI[0], "iforest": OI[1], "hgb": OI[1],
        "pca": OI[2], "ae": OI[2]}
TYPES = ["stuck", "dropout", "bias", "drift", "coupling", "runaway"]
CH_NAMES = ["v_bus", "i_load", "i_sa", "i_batt", "t_batt", "t_sa", "t_pl",
            "t_obc", "t_rad", "w_rwx", "w_rwy", "t_rwx"]
with open(args.summary, encoding="utf-8") as summary_file:
    S = json.load(summary_file)


def save(fig, name):
    fig.savefig(f"{FIG}/{name}.pdf", bbox_inches="tight")
    fig.savefig(f"{FIG}/{name}.png", bbox_inches="tight", dpi=600)
    plt.close(fig)
    print("saved", name)


def fig_a():
    d = np.load(f"{BASE}/data/telemetry_seed0.npz")
    ev = json.loads(str(d["ev_te"]))
    z = np.load(f"{BASE}/ckpt/model_seed0_pca.npz")
    att = np.nanmean(z["att_nat"], 0)
    det = z["det"]
    # pick a detected runaway event
    cand = [k for k, e in enumerate(ev) if e["type"] == "runaway" and det[k]]
    k = cand[0]; e = ev[k]
    pad = 600
    a, b = max(0, e["start"] - pad), min(len(d["Xte"]), e["end"] + pad)
    t = np.arange(a, b) * 30.0 / 3600.0
    show = [e["ch"], e["sec"], 2, 8]
    seen = []
    for c in show:
        if c not in seen:
            seen.append(c)
    fig = plt.figure(figsize=(7.0, 3.4))
    gs = fig.add_gridspec(len(seen), 2, width_ratios=[2.4, 1], wspace=0.32,
                          hspace=0.45)
    X = d["Xte"]
    for i, c in enumerate(seen):
        ax = fig.add_subplot(gs[i, 0])
        ax.plot(t, X[a:b, c], color=OI[0], lw=0.7)
        ax.axvspan(e["start"] * 30 / 3600, e["end"] * 30 / 3600,
                   color=OI[3], alpha=0.25, lw=0)
        for e2 in ev:
            if e2 is not e and a < e2["start"] < b and e2["ch"] == c:
                ax.axvspan(e2["start"] * 30 / 3600, e2["end"] * 30 / 3600,
                           color=OI[1], alpha=0.25, lw=0)
        ax.set_ylabel(CH_NAMES[c], fontsize=8)
        if i < len(seen) - 1:
            ax.set_xticklabels([])
    ax.set_xlabel("time [h]")
    ax2 = fig.add_subplot(gs[:, 1])
    aa = att[k] / att[k].sum()
    order = np.argsort(aa)
    cols = [OI[3] if j == e["ch"] else (OI[1] if j == e["sec"] else "0.6")
            for j in order]
    ax2.barh(range(12), aa[order], color=cols)
    ax2.set_yticks(range(12))
    ax2.set_yticklabels([CH_NAMES[j] for j in order], fontsize=7)
    ax2.set_xlabel("attribution share")
    save(fig, "fig_showcase")


def fig_b():
    M = np.array([[S["per_type"][m][t]["rec_ev"]["mean"] for t in TYPES]
                  for m in MODELS])
    fig, ax = plt.subplots(figsize=(4.6, 2.9))
    im = ax.imshow(M, cmap="viridis", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(6)); ax.set_xticklabels(TYPES, rotation=30, ha="right")
    ax.set_yticks(range(6)); ax.set_yticklabels([LBL[m] for m in MODELS])
    for i in range(6):
        for j in range(6):
            ax.text(j, i, f"{M[i,j]:.2f}", ha="center", va="center",
                    fontsize=7, color="white" if M[i, j] < 0.6 else "black")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("event recall")
    ax.set_xlabel("anomaly type"); ax.set_ylabel("detector")
    save(fig, "fig_detection_per_type")


def fig_c():
    x = np.arange(6); w = 0.35
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6))
    for ax, met, lab in [(axes[0], "hit3", "attribution hit@3"),
                         (axes[1], "rank", "mean rank of true channel")]:
        nat = [S["attr"][m]["native"][met]["mean"] for m in MODELS]
        nas = [S["attr"][m]["native"][met]["std"] for m in MODELS]
        occ = [S["attr"][m]["occl"][met]["mean"] for m in MODELS]
        ocs = [S["attr"][m]["occl"][met]["std"] for m in MODELS]
        ax.bar(x - w/2, nat, w, yerr=nas, color=OI[0], label="native",
               capsize=2, error_kw=dict(lw=0.7))
        ax.bar(x + w/2, occ, w, yerr=ocs, color=OI[1], label="occlusion",
               capsize=2, error_kw=dict(lw=0.7))
        ax.set_xticks(x); ax.set_xticklabels([LBL[m] for m in MODELS])
        ax.set_ylabel(lab); ax.set_xlabel("detector")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend(frameon=False, loc="lower left")
    save(fig, "fig_attr_quality")


def fig_d():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8),
                             gridspec_kw=dict(width_ratios=[1, 1.15]))
    x = np.arange(6); w = 0.35
    j = [S["stability"][m]["jaccard3"]["mean"] for m in MODELS]
    js = [S["stability"][m]["jaccard3"]["std"] for m in MODELS]
    r = [S["stability"][m]["spearman"]["mean"] for m in MODELS]
    rs = [S["stability"][m]["spearman"]["std"] for m in MODELS]
    axes[0].bar(x - w/2, j, w, yerr=js, color=OI[2], label="top-3 Jaccard",
                capsize=2, error_kw=dict(lw=0.7))
    axes[0].bar(x + w/2, r, w, yerr=rs, color=OI[4],
                label="Spearman $\\rho$", capsize=2, error_kw=dict(lw=0.7))
    axes[0].set_xticks(x); axes[0].set_xticklabels([LBL[m] for m in MODELS])
    axes[0].set_ylabel("replicate stability"); axes[0].set_xlabel("detector")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend(frameon=False, loc="upper center",
                   bbox_to_anchor=(0.5, 1.16), ncol=2)
    Mx = np.full((6, 6), np.nan)
    for i, a in enumerate(MODELS):
        Mx[i, i] = S["stability"][a]["jaccard3"]["mean"]
        for jj, b in enumerate(MODELS):
            key = f"{a}|{b}" if f"{a}|{b}" in S["cross_family"] else f"{b}|{a}"
            if key in S["cross_family"]:
                Mx[i, jj] = S["cross_family"][key]["mean"]
                Mx[jj, i] = Mx[i, jj]
    im = axes[1].imshow(Mx, cmap="viridis", vmin=0, vmax=1)
    axes[1].set_xticks(range(6)); axes[1].set_xticklabels([LBL[m] for m in MODELS])
    axes[1].set_yticks(range(6)); axes[1].set_yticklabels([LBL[m] for m in MODELS])
    for i in range(6):
        for jj in range(6):
            if np.isfinite(Mx[i, jj]):
                axes[1].text(jj, i, f"{Mx[i,jj]:.2f}", ha="center",
                             va="center", fontsize=6.5,
                             color="white" if Mx[i, jj] < 0.6 else "black")
    cb = fig.colorbar(im, ax=axes[1], fraction=0.045, pad=0.02)
    cb.set_label("top-3 Jaccard")
    axes[1].set_xlabel("detector")
    save(fig, "fig_stability")


def fig_e():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6))
    x = np.arange(6); w = 0.35
    for ax, met, lab in [(axes[0], "ndcg10", "NDCG@10"),
                         (axes[1], "p5_hisev", "precision@5 (severity 3)")]:
        b = [S["prio"][m]["baseline"][met]["mean"] for m in MODELS]
        bs = [S["prio"][m]["baseline"][met]["std"] for m in MODELS]
        a = [S["prio"][m]["aware_add"][met]["mean"] for m in MODELS]
        as_ = [S["prio"][m]["aware_add"][met]["std"] for m in MODELS]
        ax.bar(x - w/2, b, w, yerr=bs, color="0.6", label="score only",
               capsize=2, error_kw=dict(lw=0.7))
        ax.bar(x + w/2, a, w, yerr=as_, color=OI[3],
               label="explanation-aware", capsize=2, error_kw=dict(lw=0.7))
        ax.set_xticks(x); ax.set_xticklabels([LBL[m] for m in MODELS])
        ax.set_ylabel(lab); ax.set_xlabel("detector")
    axes[0].legend(frameon=False, loc="upper center",
                   bbox_to_anchor=(0.5, 1.18), ncol=2)
    save(fig, "fig_legacy_ndcg_priority")


def fig_f():
    fig, ax = plt.subplots(figsize=(3.6, 2.9))
    OFF = {"lr": (10, -16), "dtree": (6, 6), "iforest": (6, 6),
           "hgb": (-34, -8), "pca": (8, -8), "ae": (-10, 8)}
    for m in MODELS:
        fx = S["models"][m]["f1_ev"]["mean"]; fxe = S["models"][m]["f1_ev"]["std"]
        fy = S["attr"][m]["native"]["hit3"]["mean"]
        fye = S["attr"][m]["native"]["hit3"]["std"]
        ax.errorbar(fx, fy, xerr=fxe, yerr=fye, fmt="o", color=FAMC[m],
                    ms=5, capsize=2, lw=0.8)
        ax.annotate(LBL[m], (fx, fy), textcoords="offset points",
                    xytext=OFF[m], fontsize=8)
    from matplotlib.lines import Line2D
    hands = [Line2D([0], [0], marker="o", ls="", color=OI[0], label="interpretable"),
             Line2D([0], [0], marker="o", ls="", color=OI[1], label="tree ensemble"),
             Line2D([0], [0], marker="o", ls="", color=OI[2], label="reconstruction")]
    ax.legend(handles=hands, frameon=False, loc="lower right", fontsize=7)
    ax.set_xlabel("event-wise F1"); ax.set_ylabel("attribution hit@3 (native)")
    ax.set_xlim(0, 0.85); ax.set_ylim(0, 1.05)
    save(fig, "fig_tradeoff")


if __name__ == "__main__":
    for c in args.figures:
        dict(a=fig_a, b=fig_b, c=fig_c, d=fig_d, e=fig_e, f=fig_f)[c]()

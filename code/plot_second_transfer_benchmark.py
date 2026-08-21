#!/usr/bin/env python3
"""Plot saved second transfer benchmark outputs for SCI-f07."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--fig-dir", required=True)
    args = parser.parse_args()
    result_dir = Path(args.result_dir)
    fig_dir = Path(args.fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)

    bench = pd.read_csv(result_dir / "benchmark_results.csv")
    sig = pd.read_csv(result_dir / "feature_signature_audit.csv")
    runtime = pd.read_csv(result_dir / "runtime_by_stage.csv")

    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    x = range(len(bench))
    ax.bar(x, bench["precision_at_5pct_score_mean"], width=0.38, label="Score-only", color="#4c78a8")
    ax.bar(
        [i + 0.38 for i in x],
        bench["precision_at_5pct_explanation_rank_mean"],
        width=0.38,
        label="Explanation-ranked",
        color="#f58518",
    )
    ax.set_xticks([i + 0.19 for i in x])
    ax.set_xticklabels(bench["model"], rotation=25, ha="right")
    ax.set_ylim(0.0, 1.02)
    ax.set_ylabel("Precision@5%")
    ax.set_title("Second real transfer alarm-ranking comparison")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "fig_fh7_second_transfer_ranking.png", dpi=180)
    fig.savefig(fig_dir / "fig_fh7_second_transfer_ranking.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.bar(bench["model"], bench["mean_signature_cosine"].fillna(0.0), color="#59a14f")
    ax.set_ylim(0.0, 1.02)
    ax.set_ylabel("Mean cross-seed cosine")
    ax.set_title("Feature-signature stability")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_dir / "fig_fh7_second_transfer_stability.png", dpi=180)
    fig.savefig(fig_dir / "fig_fh7_second_transfer_stability.pdf")
    plt.close(fig)

    top = sig.groupby(["model", "feature"], as_index=False)["importance"].mean().sort_values("importance", ascending=False).head(12)
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    ax.barh(top["model"] + " / " + top["feature"], top["importance"], color="#b279a2")
    ax.invert_yaxis()
    ax.set_xlabel("Mean feature-signature importance")
    ax.set_title("Top transfer-benchmark explanation signatures")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_dir / "fig_fh7_second_transfer_signatures.png", dpi=180)
    fig.savefig(fig_dir / "fig_fh7_second_transfer_signatures.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.bar(runtime["stage"], runtime["wall_seconds"], color="#e15759")
    ax.set_ylabel("Wall seconds")
    ax.set_title("Second transfer runtime by stage")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_dir / "fig_fh7_second_transfer_runtime.png", dpi=180)
    fig.savefig(fig_dir / "fig_fh7_second_transfer_runtime.pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()

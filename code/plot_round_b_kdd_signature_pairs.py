#!/usr/bin/env python3
"""Render the Round B KDDCup99 within-model signature-pair audit."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd


MODEL_ORDER = ["logistic", "random_forest", "hgb", "isolation_forest"]
MODEL_LABELS = {
    "logistic": "Logistic regression",
    "random_forest": "Random forest",
    "hgb": "HGB",
    "isolation_forest": "Isolation forest",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-audit", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    pair_audit = pd.read_csv(args.pair_audit)
    pair_audit = pair_audit.loc[pair_audit["dataset"] == "kddcup99"].copy()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    supporting_font = "Liberation Sans" if "Liberation Sans" in available_fonts else "Open Sans"
    plt.rcParams.update(
        {
            "font.family": supporting_font,
            "font.size": 8.5,
            "axes.labelsize": 8.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
        }
    )
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("#D9D9D9")
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 6.3), constrained_layout=True)
    image = None

    for panel_index, (axis, model) in enumerate(zip(axes.flat, MODEL_ORDER)):
        model_pairs = pair_audit.loc[pair_audit["model"] == model]
        seeds = sorted(set(model_pairs["seed_a"]).union(model_pairs["seed_b"]))
        seed_to_index = {seed: index for index, seed in enumerate(seeds)}
        matrix = np.full((len(seeds), len(seeds)), np.nan)
        nonzero_seed = {seed: False for seed in seeds}
        for row in model_pairs.itertuples(index=False):
            index_a = seed_to_index[row.seed_a]
            index_b = seed_to_index[row.seed_b]
            if row.norm_a > 0:
                nonzero_seed[row.seed_a] = True
            if row.norm_b > 0:
                nonzero_seed[row.seed_b] = True
            if row.pair_status == "valid":
                matrix[index_a, index_b] = row.cosine
                matrix[index_b, index_a] = row.cosine
        for seed, index in seed_to_index.items():
            if nonzero_seed[seed]:
                matrix[index, index] = 1.0

        image = axis.imshow(matrix, vmin=0.0, vmax=1.0, cmap=cmap, interpolation="nearest")
        axis.set_xticks(range(len(seeds)), labels=seeds)
        axis.set_yticks(range(len(seeds)), labels=seeds)
        axis.set_xlabel("Seed")
        axis.set_ylabel("Seed")
        axis.text(
            0.5,
            1.04,
            MODEL_LABELS[model],
            transform=axis.transAxes,
            ha="center",
            va="bottom",
            fontname="Lato",
            fontweight="bold",
            fontsize=9.5,
        )
        for row_index in range(len(seeds)):
            for column_index in range(len(seeds)):
                value = matrix[row_index, column_index]
                if np.isfinite(value):
                    color = "white" if value < 0.55 else "black"
                    axis.text(
                        column_index,
                        row_index,
                        f"{value:.2f}",
                        ha="center",
                        va="center",
                        fontsize=6.5,
                        color=color,
                    )
        axis.text(
            0.5,
            -0.24,
            f"({chr(ord('a') + panel_index)})",
            transform=axis.transAxes,
            ha="center",
            va="top",
            fontweight="normal",
            fontsize=8.5,
        )

    if image is None:
        raise ValueError("No KDDCup99 pair-audit rows were available")
    colorbar = fig.colorbar(image, ax=axes, shrink=0.83, pad=0.03)
    colorbar.set_label("Within-model signature cosine")
    png_path = out_dir / "fig_kdd_signature_pairs.png"
    pdf_path = out_dir / "fig_kdd_signature_pairs.pdf"
    fig.savefig(png_path, dpi=600, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)
    print(f"KDD_SIGNATURE_PAIR_FIGURE_OK {png_path}")


if __name__ == "__main__":
    main()

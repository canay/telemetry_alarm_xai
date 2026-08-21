"""Derive the held-out synthetic test-window prevalence used in Round D closure.

This script reads the frozen seed-0--4 NPZ files and does not fit or refit a
model.  It applies the canonical window and overlap-label functions from
``common.py`` and writes one traceable JSON artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from common import window_features, window_labels


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    for seed in range(5):
        source = args.data_dir / f"telemetry_seed{seed}.npz"
        with np.load(source, allow_pickle=False) as frozen:
            _, starts = window_features(frozen["Xte"])
            labels = window_labels(starts, frozen["yte"])
        rows.append(
            {
                "seed": seed,
                "source": source.as_posix(),
                "source_sha256": sha256(source),
                "test_windows": int(labels.size),
                "positive_windows": int(labels.sum()),
                "positive_prevalence": float(labels.mean()),
            }
        )

    prevalence = np.asarray([row["positive_prevalence"] for row in rows])
    payload = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operation_id": "f07-round-d-e-closure-20260815",
        "derivation": "Frozen held-out point labels -> canonical 20-step windows at stride 5 -> any-overlap window label; no model fit or refit.",
        "seeds": rows,
        "summary": {
            "test_windows_per_seed": int(rows[0]["test_windows"]),
            "mean_positive_windows": float(
                np.mean([row["positive_windows"] for row in rows])
            ),
            "mean_positive_prevalence": float(prevalence.mean()),
            "minimum_positive_prevalence": float(prevalence.min()),
            "maximum_positive_prevalence": float(prevalence.max()),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

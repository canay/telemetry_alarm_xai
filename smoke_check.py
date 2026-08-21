"""Fast integrity checks for the curated public replication package."""

from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIRED = [
    "README.md",
    "LICENSE",
    "CITATION.cff",
    "requirements.txt",
    "ARTIFACTS.md",
    "REPRODUCE.md",
    "code/aggregate.py",
    "code/run_unit.py",
    "code/run_opssat_transfer_benchmark.py",
    "results/results_summary.json",
    "results/openml_results.json",
    "results/opssat_transfer_benchmark/opssat_manifest.json",
    "results/second_transfer_benchmark_audit_rerun/second_transfer_manifest.json",
]


def main() -> None:
    missing = [item for item in REQUIRED if not (ROOT / item).is_file()]
    if missing:
        raise SystemExit(f"Missing required artifacts: {missing}")

    for path in sorted((ROOT / "code").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for relative in [
        "results/results_summary.json",
        "results/openml_results.json",
        "results/opssat_transfer_benchmark/opssat_manifest.json",
        "results/second_transfer_benchmark_audit_rerun/second_transfer_manifest.json",
    ]:
        with (ROOT / relative).open(encoding="utf-8") as handle:
            json.load(handle)

    print("SMOKE_CHECK_PASS")


if __name__ == "__main__":
    main()

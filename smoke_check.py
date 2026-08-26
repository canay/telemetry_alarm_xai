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
    "PROTOCOL_V1_1.md",
    "CONFIRMATORY_PLAN.json",
    "POWER_PLAN_V4.json",
    "code/aggregate.py",
    "code/run_unit.py",
    "code/run_opssat_transfer_benchmark.py",
    "code/run_confirmation_v4.py",
    "code/confirmatory_analysis_v4.py",
    "results/results_summary.json",
    "results/openml_results.json",
    "results/opssat_transfer_benchmark/opssat_manifest.json",
    "results/second_transfer_benchmark_audit_rerun/second_transfer_manifest.json",
    "results/scenario_utility_v1_2/replication_property_tests.json",
    "results/scenario_utility_v1_2/confirmatory_failure.json",
    "results/scenario_utility_v1_2/manuscript_summary.json",
    "results/scenario_utility_v1_2/scenario_model_gains.png",
    "results/scenario_utility_v1_2/scenario_model_gains.pdf",
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
        "CONFIRMATORY_PLAN.json",
        "POWER_PLAN_V4.json",
        "results/v3_discovery_construct_validity.json",
        "results/v3_discovery_property_tests.json",
        "results/scenario_utility_v1_2/replication_property_tests.json",
        "results/scenario_utility_v1_2/confirmatory_failure.json",
        "results/scenario_utility_v1_2/manuscript_summary.json",
    ]:
        with (ROOT / relative).open(encoding="utf-8") as handle:
            json.load(handle)

    failure = json.loads(
        (ROOT / "results/scenario_utility_v1_2/confirmatory_failure.json").read_text(
            encoding="utf-8"
        )
    )
    if failure.get("status") != "NOT_CONFIRMED_PROPERTY_GATE":
        raise SystemExit("Unexpected confirmation status")
    if failure.get("endpoint_analysis_performed") is not False:
        raise SystemExit("Confirmation closure must not contain endpoint analysis")
    if failure.get("rescue_change_performed") is not False:
        raise SystemExit("Confirmation closure must remain rescue-free")

    print("SMOKE_CHECK_PASS")


if __name__ == "__main__":
    main()

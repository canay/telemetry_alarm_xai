"""Fast integrity checks for the curated public replication package."""

from __future__ import annotations

import ast
import hashlib
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
    "PROTOCOL_V2_0.md",
    "CONFIRMATORY_PLAN_V5.json",
    "POWER_PLAN_V5.json",
    "PILOT_PROPERTY_V5.json",
    "code/aggregate.py",
    "code/run_unit.py",
    "code/run_opssat_transfer_benchmark.py",
    "code/run_confirmation_v4.py",
    "code/confirmatory_analysis_v4.py",
    "results/results_summary.json",
    "results/openml_results.json",
    "results/opssat_transfer_benchmark/opssat_manifest.json",
    "results/opssat_transfer_benchmark/signature_repair_provenance.json",
    "results/second_transfer_benchmark_audit_rerun/second_transfer_manifest.json",
    "results/second_transfer_benchmark_audit_rerun/signature_repair_provenance.json",
    "results/scenario_utility_v1_2/replication_property_tests.json",
    "results/scenario_utility_v1_2/confirmatory_failure.json",
    "results/scenario_utility_v1_2/manuscript_summary.json",
    "results/scenario_utility_v1_2/scenario_model_gains.png",
    "results/scenario_utility_v1_2/scenario_model_gains.pdf",
    "results/scenario_utility_v2_1/v5_property_tests.json",
    "results/scenario_utility_v2_1/v5_run_manifest.json",
    "results/scenario_utility_v2_1/v5_confirmatory_failure.json",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    missing = [item for item in REQUIRED if not (ROOT / item).is_file()]
    if missing:
        raise SystemExit(f"Missing required artifacts: {missing}")

    checksum_lines = (ROOT / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    checksum_inventory = {}
    for line in checksum_lines:
        expected, relative = line.split("  ", 1)
        checksum_inventory[relative] = expected
    for relative in REQUIRED:
        if relative not in checksum_inventory:
            raise SystemExit(f"Required artifact absent from checksum inventory: {relative}")
    for relative, expected in checksum_inventory.items():
        path = ROOT / relative
        if not path.is_file() or sha256(path) != expected:
            raise SystemExit(f"Checksum mismatch: {relative}")

    for path in sorted((ROOT / "code").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for relative in [
        "results/results_summary.json",
        "results/openml_results.json",
        "results/opssat_transfer_benchmark/opssat_manifest.json",
        "results/opssat_transfer_benchmark/signature_repair_provenance.json",
        "results/second_transfer_benchmark_audit_rerun/second_transfer_manifest.json",
        "results/second_transfer_benchmark_audit_rerun/signature_repair_provenance.json",
        "CONFIRMATORY_PLAN.json",
        "POWER_PLAN_V4.json",
        "results/v3_discovery_construct_validity.json",
        "results/v3_discovery_property_tests.json",
        "results/scenario_utility_v1_2/replication_property_tests.json",
        "results/scenario_utility_v1_2/confirmatory_failure.json",
        "results/scenario_utility_v1_2/manuscript_summary.json",
        "CONFIRMATORY_PLAN_V5.json",
        "POWER_PLAN_V5.json",
        "PILOT_PROPERTY_V5.json",
        "results/scenario_utility_v2_1/v5_property_tests.json",
        "results/scenario_utility_v2_1/v5_run_manifest.json",
        "results/scenario_utility_v2_1/v5_confirmatory_failure.json",
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

    v5_failure = json.loads(
        (ROOT / "results/scenario_utility_v2_1/v5_confirmatory_failure.json").read_text(
            encoding="utf-8"
        )
    )
    if v5_failure.get("status") != "NOT_CONFIRMED_PROPERTY_GATE":
        raise SystemExit("Unexpected V5 confirmation status")
    if v5_failure.get("classification") != "FIXED_GATE_MISSPECIFIED":
        raise SystemExit("Unexpected V5 gate classification")
    if v5_failure.get("endpoint_analysis_performed") is not False:
        raise SystemExit("V5 closure must not contain endpoint analysis")
    if v5_failure.get("rescue_change_performed") is not False:
        raise SystemExit("V5 closure must remain rescue-free")
    for field, relative in (
        (
            "published_property_tests_sha256",
            "results/scenario_utility_v2_1/v5_property_tests.json",
        ),
        (
            "published_run_manifest_sha256",
            "results/scenario_utility_v2_1/v5_run_manifest.json",
        ),
    ):
        if v5_failure.get(field) != sha256(ROOT / relative):
            raise SystemExit(f"V5 published evidence hash mismatch: {relative}")
    v5_property = json.loads(
        (ROOT / "results/scenario_utility_v2_1/v5_property_tests.json").read_text(
            encoding="utf-8"
        )
    )
    if v5_property.get("status") != "FAIL" or v5_property.get("n_checks") != 3089:
        raise SystemExit("Unexpected V5 property result")
    if v5_property.get("failed") != v5_failure.get("failed_property_checks"):
        raise SystemExit("V5 failure record does not match the property result")
    v5_manifest = json.loads(
        (ROOT / "results/scenario_utility_v2_1/v5_run_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if v5_manifest.get("status") != "NOT_CONFIRMED_PROPERTY_GATE":
        raise SystemExit("Unexpected V5 run-manifest status")

    print("SMOKE_CHECK_PASS")


if __name__ == "__main__":
    main()

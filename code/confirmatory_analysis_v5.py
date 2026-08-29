"""Frozen five-endpoint confirmation for untouched V5 seeds 300--319.

The governing population is the five-model episode-weighted pooled queue.
Six-model episode-weighted and seven-trajectory-weighted results are mandatory
sensitivities and can never upgrade the primary decision.

Operation: f07-v5-power-mismatch-independent-review-20260830
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np

import criticality_analysis_v5 as analysis_v5
from criticality_analysis_v4 import confirmatory_decision, write_csv, write_json


SEEDS = tuple(range(300, 320))
PRIMARY_MODELS = ("lr", "iforest", "hgb", "pca", "ae")
ALL_MODELS = ("lr", "dtree", "iforest", "hgb", "pca", "ae")
SCENARIOS = ("platform_survival", "payload_first")
POLICIES = ("score_only", "occlusion_context")
REPLICATES = tuple(range(7))
RELEASE_TAG = "v2.0.0"
REPO = "canay/telemetry_alarm_xai"
PLAN_NAME = "CONFIRMATORY_PLAN_V5.json"
DECISION_METHOD = "one_sample_student_t_lower_bound"
REQUIRED_FROZEN_FILES = {
    ".gitattributes",
    "code/common.py",
    "code/models.py",
    "code/telemetry_generator.py",
    "code/criticality_generator.py",
    "code/criticality_generator_v5.py",
    "code/run_criticality_unit.py",
    "code/run_criticality_unit_v5.py",
    "code/criticality_analysis_v4.py",
    "code/criticality_property_v5.py",
    "code/criticality_analysis_v5.py",
    "code/confirmatory_analysis_v5.py",
    "code/run_v5_development.py",
    "code/power_freeze_v5.py",
    "code/test_v5_contract.py",
    "PROTOCOL_V2_0.md",
    "POWER_PLAN_V5.json",
    "PILOT_PROPERTY_V5.json",
}
EXPECTED_KILL_SWITCHES = {
    "null_false_gain_rate_gt_0_05",
    "within_type_utility_null_false_gain_rate_gt_0_05",
    "information_contrast_null_false_gain_rate_gt_0_05",
    "metric_redundancy_without_scenario_disagreement",
    "systematic_native_occlusion_conflict",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str, cwd: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(cwd), *args], text=True, encoding="utf-8"
    ).strip()


def verify_release(args: argparse.Namespace, manifest: dict) -> dict:
    if args.release_tag != RELEASE_TAG:
        raise ValueError(f"confirmatory release tag must be {RELEASE_TAG}")
    if not re.fullmatch(r"[0-9a-f]{40}", args.release_commit):
        raise ValueError("release commit must be a lowercase full SHA-1")
    for key, expected in (
        ("release_tag", args.release_tag),
        ("release_commit", args.release_commit),
        ("seeds", list(SEEDS)),
        ("primary_models", list(PRIMARY_MODELS)),
        ("n_test_replicates", len(REPLICATES)),
        ("minimum_pooled_episodes", 20),
        ("null_draws", 200),
    ):
        if manifest.get(key) != expected:
            raise RuntimeError(f"run manifest mismatch: {key}")
    if git("rev-parse", "HEAD", cwd=args.release_root) != args.release_commit:
        raise RuntimeError("release checkout HEAD does not match supplied commit")
    if git("rev-list", "-n", "1", args.release_tag, cwd=args.release_root) != args.release_commit:
        raise RuntimeError("release tag does not resolve to supplied commit")
    if git("status", "--porcelain", cwd=args.release_root):
        raise RuntimeError("release checkout is not clean")

    plan_path = args.release_root / PLAN_NAME
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for key, expected in (
        ("release_tag", RELEASE_TAG),
        ("seeds", list(SEEDS)),
        ("confirmation_n", len(SEEDS)),
        ("decision_method", DECISION_METHOD),
        ("primary_models", list(PRIMARY_MODELS)),
        ("all_models", list(ALL_MODELS)),
        ("n_test_replicates", len(REPLICATES)),
    ):
        if plan.get(key) != expected:
            raise RuntimeError(f"frozen confirmatory plan mismatch: {key}")
    if set(plan.get("code_sha256", {})) != REQUIRED_FROZEN_FILES:
        raise RuntimeError("frozen confirmatory file set mismatch")
    for relative, expected in plan["code_sha256"].items():
        if sha256(args.release_root / relative) != expected:
            raise RuntimeError(f"frozen code hash mismatch: {relative}")
    if sha256(Path(analysis_v5.__file__).resolve()) != plan["code_sha256"][
        "code/criticality_analysis_v5.py"
    ]:
        raise RuntimeError("runtime V5 analysis module is not the released file")

    origin = git("remote", "get-url", "origin", cwd=args.release_root)
    if origin not in {
        "https://github.com/canay/telemetry_alarm_xai.git",
        "git@github.com:canay/telemetry_alarm_xai.git",
    }:
        raise RuntimeError(f"unexpected release origin: {origin}")
    remote_tag_line = git(
        "ls-remote", "--tags", "origin", f"refs/tags/{RELEASE_TAG}", cwd=args.release_root
    )
    remote_tag = remote_tag_line.split()[0] if remote_tag_line else ""
    api_tag = subprocess.check_output(
        ["gh", "api", f"repos/{REPO}/git/ref/tags/{RELEASE_TAG}", "--jq", ".object.sha"],
        text=True,
        encoding="utf-8",
    ).strip()
    if remote_tag != args.release_commit or api_tag != args.release_commit:
        raise RuntimeError("remote release tag does not bind supplied commit")
    release = json.loads(
        subprocess.check_output(
            [
                "gh", "release", "view", RELEASE_TAG, "--repo", REPO,
                "--json", "tagName,publishedAt,url,body",
            ],
            text=True,
            encoding="utf-8",
        )
    )
    if release.get("publishedAt") != manifest.get("release_published_at_utc"):
        raise RuntimeError("run manifest release time is not the remote release time")
    plan_match = re.search(r"plan_sha256=([0-9a-f]{64})", release.get("body", ""))
    if not plan_match or plan_match.group(1) != sha256(plan_path):
        raise RuntimeError("remote release body does not bind the frozen plan")

    published = datetime.fromisoformat(
        manifest["release_published_at_utc"].replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    for relative, expected in manifest.get("artifact_sha256", {}).items():
        path = args.run_root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"registered confirmatory artifact mismatch: {relative}")
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) <= published:
            raise RuntimeError(f"registered confirmatory artifact predates release: {relative}")
    return plan


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def policy_index(rows: list[dict[str, str]]) -> dict[tuple[int, str, str, str], float]:
    selected = [
        row for row in rows
        if row["model"] in ALL_MODELS
        and row["scenario"] in SCENARIOS
        and row["policy"] in POLICIES
    ]
    keys = [
        (int(row["seed"]), row["model"], row["scenario"], row["policy"])
        for row in selected
    ]
    expected = {
        (seed, model, scenario, policy)
        for seed in SEEDS for model in ALL_MODELS
        for scenario in SCENARIOS for policy in POLICIES
    }
    duplicates = [key for key, count in Counter(keys).items() if count != 1]
    if duplicates or set(keys) != expected:
        raise RuntimeError(
            f"policy cell contract failed duplicates={duplicates[:3]} "
            f"missing={sorted(expected - set(keys))[:3]}"
        )
    return {key: float(row["muc_auc_0_40"]) for key, row in zip(keys, selected)}


def utility_null_index(
    rows: list[dict[str, str]], null_draws: int
) -> dict[tuple[int, str, str], float]:
    grouped: dict[tuple[int, str, str], list[float]] = {}
    draws: dict[tuple[int, str, str], set[int]] = {}
    for row in rows:
        key = (int(row["seed"]), row["model"], row["scenario"])
        if key[0] not in SEEDS or key[1] not in ALL_MODELS or key[2] not in SCENARIOS:
            raise RuntimeError("utility-null file contains out-of-plan cell")
        grouped.setdefault(key, []).append(float(row["gain"]))
        draws.setdefault(key, set()).add(int(row["draw"]))
    expected = {
        (seed, model, scenario)
        for seed in SEEDS for model in ALL_MODELS for scenario in SCENARIOS
    }
    if set(grouped) != expected:
        raise RuntimeError("utility-null cell set is incomplete")
    for key in expected:
        if draws[key] != set(range(null_draws)) or len(grouped[key]) != null_draws:
            raise RuntimeError(f"utility-null draw contract mismatch: {key}")
    return {key: float(np.mean(values)) for key, values in grouped.items()}


def endpoint_row(
    seed: int,
    platform_raw: float,
    payload_raw: float,
    platform_null: float,
    payload_null: float,
) -> dict:
    return {
        "seed": seed,
        "platform_raw": platform_raw,
        "payload_raw": payload_raw,
        "payload_harm_raw": -payload_raw,
        "scenario_contrast_raw": platform_raw - payload_raw,
        "platform_null": platform_null,
        "payload_null": payload_null,
        "platform_information": platform_raw - platform_null,
        "payload_information": payload_raw - payload_null,
    }


def pooled_endpoints(
    index: dict[tuple[int, str, str, str], float],
    utility_null: dict[tuple[int, str, str], float],
    models: tuple[str, ...],
) -> list[dict]:
    rows = []
    for seed in SEEDS:
        raw = {
            scenario: float(np.mean([
                index[(seed, model, scenario, "occlusion_context")]
                - index[(seed, model, scenario, "score_only")]
                for model in models
            ]))
            for scenario in SCENARIOS
        }
        null = {
            scenario: float(np.mean([
                utility_null[(seed, model, scenario)] for model in models
            ]))
            for scenario in SCENARIOS
        }
        rows.append(endpoint_row(
            seed,
            raw["platform_survival"],
            raw["payload_first"],
            null["platform_survival"],
            null["payload_first"],
        ))
    return rows


def trajectory_weighted_endpoints(
    rows: list[dict[str, str]], models: tuple[str, ...]
) -> list[dict]:
    keys = [
        (int(row["seed"]), row["model"], int(row["replicate"]), row["scenario"])
        for row in rows
    ]
    expected = {
        (seed, model, replicate, scenario)
        for seed in SEEDS for model in ALL_MODELS
        for replicate in REPLICATES for scenario in SCENARIOS
    }
    duplicates = [key for key, count in Counter(keys).items() if count != 1]
    if duplicates or set(keys) != expected:
        raise RuntimeError(
            f"per-replicate sensitivity contract failed duplicates={duplicates[:3]} "
            f"missing={sorted(expected - set(keys))[:3]}"
        )
    lookup = {key: row for key, row in zip(keys, rows)}
    result = []
    for seed in SEEDS:
        raw = {}
        null = {}
        for scenario in SCENARIOS:
            model_raw = []
            model_null = []
            for model in models:
                model_rows = [lookup[(seed, model, replicate, scenario)] for replicate in REPLICATES]
                model_raw.append(float(np.mean([float(row["raw_gain"]) for row in model_rows])))
                model_null.append(float(np.mean([
                    float(row["mean_within_type_utility_null_gain"])
                    for row in model_rows
                ])))
            raw[scenario] = float(np.mean(model_raw))
            null[scenario] = float(np.mean(model_null))
        result.append(endpoint_row(
            seed,
            raw["platform_survival"],
            raw["payload_first"],
            null["platform_survival"],
            null["payload_first"],
        ))
    return result


def decisions(rows: list[dict]) -> dict[str, dict]:
    endpoints = (
        "scenario_contrast_raw",
        "platform_raw",
        "payload_harm_raw",
        "platform_information",
        "payload_information",
    )
    return {
        endpoint: confirmatory_decision([float(row[endpoint]) for row in rows])
        for endpoint in endpoints
    }


def disagreements(primary: dict, sensitivity: dict) -> dict:
    return {
        endpoint: {
            "primary_pass": primary[endpoint]["pass"],
            "sensitivity_pass": sensitivity[endpoint]["pass"],
            "primary_mean": primary[endpoint]["mean"],
            "sensitivity_mean": sensitivity[endpoint]["mean"],
        }
        for endpoint in primary
        if primary[endpoint]["pass"] != sensitivity[endpoint]["pass"]
        or np.sign(primary[endpoint]["mean"]) != np.sign(sensitivity[endpoint]["mean"])
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--release-commit", required=True)
    args = parser.parse_args()

    manifest = json.loads((args.run_root / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    plan = verify_release(args, manifest)
    property_result = json.loads(
        (args.run_root / "metrics" / "property_tests.json").read_text(encoding="utf-8")
    )
    checks = {
        "status": "PASS",
        "generator_seeds": list(SEEDS),
        "model_seeds": list(SEEDS),
        "models": list(ALL_MODELS),
        "n_test_replicates": len(REPLICATES),
        "minimum_pooled_episodes": 20,
    }
    for key, expected in checks.items():
        if property_result.get(key) != expected:
            raise RuntimeError(f"confirmatory property contract mismatch: {key}")

    construct = json.loads(
        (args.run_root / "metrics" / "construct_validity.json").read_text(encoding="utf-8")
    )
    expected_controls = {"permuted_context", "noise_attribution_context"}
    expected_scenarios = set(SCENARIOS)
    raw_control_rates = construct["null_false_gain_rates_by_control_and_scenario"]
    information_rates = construct["information_contrast_null_false_gain_rates"]
    utility_rates = construct["within_type_utility_null_false_gain_rates"]
    if set(raw_control_rates) != expected_controls or set(information_rates) != expected_controls:
        raise RuntimeError("confirmatory null control-family set mismatch")
    if any(set(values) != expected_scenarios for values in raw_control_rates.values()):
        raise RuntimeError("raw null scenario set mismatch")
    if any(set(values) != expected_scenarios for values in information_rates.values()):
        raise RuntimeError("information-null scenario set mismatch")
    if set(utility_rates) != expected_scenarios:
        raise RuntimeError("within-type utility-null scenario set mismatch")
    null_rates = [rate for values in raw_control_rates.values() for rate in values.values()]
    null_rates.extend(rate for values in information_rates.values() for rate in values.values())
    null_rates.extend(utility_rates.values())
    if max(null_rates) > 0.05:
        raise RuntimeError(f"confirmatory null false-gain gate failed: {max(null_rates)}")
    if set(construct["kill_switches"]) != EXPECTED_KILL_SWITCHES:
        raise RuntimeError("confirmatory construct kill-switch set mismatch")
    fired = {key: value for key, value in construct["kill_switches"].items() if value}
    if fired:
        raise RuntimeError(f"confirmatory construct kill switch fired: {fired}")
    legacy = construct.get("legacy_universal_uplift_diagnostics", {})
    if legacy.get("status") != "NOT_A_FROZEN_ENDPOINT":
        raise RuntimeError("legacy universal-uplift diagnostic is not safely labelled")

    index = policy_index(read_rows(args.run_root / "metrics" / "policy_summary.csv"))
    utility_null = utility_null_index(
        read_rows(args.run_root / "metrics" / "utility_permutation_null.csv"),
        manifest["null_draws"],
    )
    replicate_rows = read_rows(
        args.run_root / "metrics" / "per_replicate_sensitivity.csv"
    )
    primary_rows = pooled_endpoints(index, utility_null, PRIMARY_MODELS)
    six_model_rows = pooled_endpoints(index, utility_null, ALL_MODELS)
    trajectory_rows = trajectory_weighted_endpoints(replicate_rows, PRIMARY_MODELS)
    primary_decisions = decisions(primary_rows)
    six_model_decisions = decisions(six_model_rows)
    trajectory_decisions = decisions(trajectory_rows)
    success = all(result["pass"] for result in primary_decisions.values())
    output = {
        "schema_version": 5,
        "status": "CONFIRMED" if success else "NOT_CONFIRMED",
        "not_universal_xai_benefit": True,
        "claim": (
            "controlled synthetic score-baseline scenario reversal with positive "
            "information relative to the within-replicate fault-type utility null"
        ),
        "release_tag": args.release_tag,
        "release_commit": args.release_commit,
        "release_url": manifest["release_url"],
        "release_published_at_utc": manifest["release_published_at_utc"],
        "plan_sha256": sha256(args.release_root / PLAN_NAME),
        "seeds": list(SEEDS),
        "primary_models": list(PRIMARY_MODELS),
        "all_five_conditions_required": True,
        "primary_population": "five-model episode-weighted pooled queue",
        "decisions": primary_decisions,
        "six_model_episode_weighted_mandatory_sensitivity": six_model_decisions,
        "five_model_trajectory_weighted_mandatory_sensitivity": trajectory_decisions,
        "six_model_disagreement": disagreements(primary_decisions, six_model_decisions),
        "trajectory_weighted_disagreement": disagreements(primary_decisions, trajectory_decisions),
        "property_gate": property_result["status"],
        "property_checks": property_result["n_checks"],
        "maximum_null_false_gain_rate": max(null_rates),
        "decision_method": plan["decision_method"],
    }
    write_csv(args.run_root / "metrics" / "confirmatory_primary_per_seed.csv", primary_rows)
    write_csv(args.run_root / "metrics" / "confirmatory_six_model_per_seed.csv", six_model_rows)
    write_csv(args.run_root / "metrics" / "confirmatory_trajectory_weighted_per_seed.csv", trajectory_rows)
    write_json(args.run_root / "metrics" / "confirmatory_decision.json", output)
    print(json.dumps(output, indent=2, sort_keys=True))
    if not success:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

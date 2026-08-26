"""Frozen five-endpoint confirmation for untouched V4 seeds 10--29.

Operation: f07-criticality-v4-pre-freeze-repair-20260826
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

import criticality_analysis_v4 as analysis_v4
from criticality_analysis_v4 import confirmatory_decision, write_csv, write_json


SEEDS = tuple(range(10, 30))
PRIMARY_MODELS = ("lr", "iforest", "hgb", "pca", "ae")
ALL_MODELS = ("lr", "dtree", "iforest", "hgb", "pca", "ae")
SCENARIOS = ("platform_survival", "payload_first")
POLICIES = ("score_only", "occlusion_context")
RELEASE_TAG = "v1.1.0"
REPO = "canay/telemetry_alarm_xai"
DECISION_METHOD = "one_sample_student_t_lower_bound"
REQUIRED_FROZEN_FILES = {
    ".gitattributes",
    "code/common.py",
    "code/models.py",
    "code/telemetry_generator.py",
    "code/criticality_generator.py",
    "code/run_criticality_unit.py",
    "code/criticality_analysis_v4.py",
    "code/confirmatory_analysis_v4.py",
    "code/run_confirmation_v4.py",
    "code/power_freeze_v4.py",
    "PROTOCOL_V1_1.md",
    "POWER_PLAN_V4.json",
}
EXPECTED_KILL_SWITCHES = {
    "null_false_gain_rate_gt_0_05",
    "within_type_utility_null_false_gain_rate_gt_0_05",
    "information_contrast_null_false_gain_rate_gt_0_05",
    "metric_redundancy_without_scenario_disagreement",
    "systematic_native_occlusion_conflict",
    "no_positive_primary_omnibus_for_power",
    "no_positive_tie_eligible_sensitivity_for_power",
}
ALLOWED_TRUE_KILL_SWITCHES = {
    "no_positive_primary_omnibus_for_power",
    "no_positive_tie_eligible_sensitivity_for_power",
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
    if manifest.get("release_tag") != args.release_tag:
        raise RuntimeError("run manifest release tag mismatch")
    if manifest.get("release_commit") != args.release_commit:
        raise RuntimeError("run manifest release commit mismatch")
    if manifest.get("seeds") != list(SEEDS):
        raise RuntimeError("run manifest seed set is not exactly 10-29")
    if manifest.get("primary_models") != list(PRIMARY_MODELS):
        raise RuntimeError("run manifest primary-model set mismatch")
    if manifest.get("amplitude_scale") != 1.0:
        raise RuntimeError("confirmatory amplitude_scale must equal 1.0")
    if manifest.get("null_draws") != 200:
        raise RuntimeError("confirmatory null_draws must equal 200")
    if git("rev-parse", "HEAD", cwd=args.release_root) != args.release_commit:
        raise RuntimeError("release checkout HEAD does not match supplied commit")
    if git("rev-list", "-n", "1", args.release_tag, cwd=args.release_root) != args.release_commit:
        raise RuntimeError("release tag does not resolve to supplied commit")
    if git("status", "--porcelain", "--untracked-files=no", cwd=args.release_root):
        raise RuntimeError("release checkout has tracked modifications")

    plan_path = args.release_root / "CONFIRMATORY_PLAN.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("release_tag") != RELEASE_TAG or plan.get("seeds") != list(SEEDS):
        raise RuntimeError("frozen confirmatory plan identity mismatch")
    if set(plan.get("code_sha256", {})) != REQUIRED_FROZEN_FILES:
        raise RuntimeError("frozen confirmatory file set mismatch")
    if plan.get("decision_method") != DECISION_METHOD:
        raise RuntimeError("frozen decision method mismatch")
    for relative, expected in plan["code_sha256"].items():
        observed = sha256(args.release_root / relative)
        if observed != expected:
            raise RuntimeError(f"frozen code hash mismatch: {relative}")
    if sha256(Path(analysis_v4.__file__).resolve()) != plan["code_sha256"][
        "code/criticality_analysis_v4.py"
    ]:
        raise RuntimeError("runtime analysis module is not the released file")

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
                "gh",
                "release",
                "view",
                RELEASE_TAG,
                "--repo",
                REPO,
                "--json",
                "tagName,publishedAt,url,body",
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
    for seed in SEEDS:
        relative = f"data/telemetry_seed{seed}.npz"
        path = args.run_root / relative
        if not path.exists():
            raise RuntimeError(f"missing confirmatory data file: {relative}")
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified <= published:
            raise RuntimeError(f"confirmatory data predates public release: {relative}")
        if manifest.get("artifact_sha256", {}).get(relative) != sha256(path):
            raise RuntimeError(f"confirmatory data hash mismatch: {relative}")
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
    observed_seeds = {int(row["seed"]) for row in rows}
    if observed_seeds != set(SEEDS):
        raise RuntimeError(f"policy_summary seed set mismatch: {sorted(observed_seeds)}")
    selected = [
        row
        for row in rows
        if row["model"] in ALL_MODELS
        and row["scenario"] in SCENARIOS
        and row["policy"] in POLICIES
    ]
    keys = [
        (int(row["seed"]), row["model"], row["scenario"], row["policy"])
        for row in selected
    ]
    duplicates = [key for key, count in Counter(keys).items() if count != 1]
    if duplicates:
        raise RuntimeError(f"duplicate policy cells: {duplicates[:5]}")
    expected = {
        (seed, model, scenario, policy)
        for seed in SEEDS
        for model in ALL_MODELS
        for scenario in SCENARIOS
        for policy in POLICIES
    }
    if set(keys) != expected:
        missing = sorted(expected - set(keys))
        extra = sorted(set(keys) - expected)
        raise RuntimeError(f"policy cell mismatch missing={missing[:5]} extra={extra[:5]}")
    return {key: float(row["muc_auc_0_40"]) for key, row in zip(keys, selected)}


def utility_null_index(
    rows: list[dict[str, str]], null_draws: int
) -> dict[tuple[int, str, str], float]:
    grouped: dict[tuple[int, str, str], list[float]] = {}
    draws: dict[tuple[int, str, str], set[int]] = {}
    for row in rows:
        seed = int(row["seed"])
        model = row["model"]
        scenario = row["scenario"]
        if seed not in SEEDS or model not in ALL_MODELS or scenario not in SCENARIOS:
            raise RuntimeError("utility-null file contains out-of-plan cell")
        key = (seed, model, scenario)
        grouped.setdefault(key, []).append(float(row["gain"]))
        draws.setdefault(key, set()).add(int(row["draw"]))
    expected = {
        (seed, model, scenario)
        for seed in SEEDS
        for model in ALL_MODELS
        for scenario in SCENARIOS
    }
    if set(grouped) != expected:
        raise RuntimeError("utility-null cell set is incomplete")
    for key in expected:
        if draws[key] != set(range(null_draws)) or len(grouped[key]) != null_draws:
            raise RuntimeError(f"utility-null draw contract mismatch: {key}")
    return {key: float(np.mean(values)) for key, values in grouped.items()}


def per_seed_endpoints(
    index: dict[tuple[int, str, str, str], float],
    utility_null: dict[tuple[int, str, str], float],
    models: tuple[str, ...],
) -> list[dict]:
    result = []
    for seed in SEEDS:
        platform_raw = float(
            np.mean(
                [
                    index[(seed, model, "platform_survival", "occlusion_context")]
                    - index[(seed, model, "platform_survival", "score_only")]
                    for model in models
                ]
            )
        )
        payload_raw = float(
            np.mean(
                [
                    index[(seed, model, "payload_first", "occlusion_context")]
                    - index[(seed, model, "payload_first", "score_only")]
                    for model in models
                ]
            )
        )
        platform_null = float(
            np.mean([utility_null[(seed, model, "platform_survival")] for model in models])
        )
        payload_null = float(
            np.mean([utility_null[(seed, model, "payload_first")] for model in models])
        )
        result.append(
            {
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
        )
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
    if property_result.get("status") != "PASS":
        raise RuntimeError("confirmatory property gate is not PASS")
    if property_result.get("generator_seeds") != list(SEEDS):
        raise RuntimeError("property generator seeds are not exactly 10-29")
    if property_result.get("model_seeds") != list(SEEDS):
        raise RuntimeError("property model seeds are not exactly 10-29")
    if property_result.get("models") != list(ALL_MODELS):
        raise RuntimeError("property model list mismatch")
    if property_result.get("expected_amplitude_scale") != 1.0:
        raise RuntimeError("property amplitude contract mismatch")
    expected_amplitudes = {str(seed): 1.0 for seed in SEEDS}
    if property_result.get("amplitude_scales") != expected_amplitudes:
        raise RuntimeError("observed per-seed amplitude scales are not all 1.0")

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
    null_rates = [
        rate for values in raw_control_rates.values() for rate in values.values()
    ]
    null_rates.extend(
        rate for values in information_rates.values() for rate in values.values()
    )
    null_rates.extend(utility_rates.values())
    if max(null_rates) > 0.05:
        raise RuntimeError(f"confirmatory null false-gain gate failed: {max(null_rates)}")
    if set(construct["kill_switches"]) != EXPECTED_KILL_SWITCHES:
        raise RuntimeError("confirmatory construct kill-switch set mismatch")
    forbidden_kills = {
        key: value
        for key, value in construct["kill_switches"].items()
        if value and key not in ALLOWED_TRUE_KILL_SWITCHES
    }
    if forbidden_kills:
        raise RuntimeError(f"confirmatory construct kill switch fired: {forbidden_kills}")

    index = policy_index(read_rows(args.run_root / "metrics" / "policy_summary.csv"))
    utility_null = utility_null_index(
        read_rows(args.run_root / "metrics" / "utility_permutation_null.csv"),
        manifest["null_draws"],
    )
    primary_rows = per_seed_endpoints(index, utility_null, PRIMARY_MODELS)
    six_model_rows = per_seed_endpoints(index, utility_null, ALL_MODELS)
    primary_decisions = decisions(primary_rows)
    sensitivity_decisions = decisions(six_model_rows)
    success = all(result["pass"] for result in primary_decisions.values())
    sensitivity_disagreement = {
        endpoint: {
            "primary_pass": primary_decisions[endpoint]["pass"],
            "six_model_pass": sensitivity_decisions[endpoint]["pass"],
            "primary_mean": primary_decisions[endpoint]["mean"],
            "six_model_mean": sensitivity_decisions[endpoint]["mean"],
        }
        for endpoint in primary_decisions
        if primary_decisions[endpoint]["pass"] != sensitivity_decisions[endpoint]["pass"]
        or np.sign(primary_decisions[endpoint]["mean"])
        != np.sign(sensitivity_decisions[endpoint]["mean"])
    }
    output = {
        "schema_version": 4,
        "status": "CONFIRMED" if success else "NOT_CONFIRMED",
        "claim": (
            "operational score-baseline reversal with positive information over "
            "within-type utility permutation in both scenarios"
        ),
        "release_tag": args.release_tag,
        "release_commit": args.release_commit,
        "release_url": manifest["release_url"],
        "release_published_at_utc": manifest["release_published_at_utc"],
        "plan_sha256": sha256(args.release_root / "CONFIRMATORY_PLAN.json"),
        "seeds": list(SEEDS),
        "primary_models": list(PRIMARY_MODELS),
        "all_five_conditions_required": True,
        "decisions": primary_decisions,
        "six_model_mandatory_sensitivity": sensitivity_decisions,
        "six_model_disagreement": sensitivity_disagreement,
        "property_gate": property_result["status"],
        "maximum_null_false_gain_rate": max(null_rates),
        "decision_method": plan["decision_method"],
    }
    write_csv(args.run_root / "metrics" / "confirmatory_per_seed.csv", primary_rows)
    write_csv(
        args.run_root / "metrics" / "confirmatory_six_model_per_seed.csv",
        six_model_rows,
    )
    write_json(args.run_root / "metrics" / "confirmatory_decision.json", output)
    print(json.dumps(output, indent=2, sort_keys=True))
    if not success:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

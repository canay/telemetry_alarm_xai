"""Endpoint-blind analyzability pilot for the prospective V5 design.

This program reports only generator structure, episode counts, thresholds, and
runtime.  It neither constructs policy scores nor evaluates utilities/nulls.

Operation: f07-prospective-confirmation-v5-20260828
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from criticality_analysis_v4 import parse_seed_spec, write_json
from criticality_generator_v5 import EVENTS_PER_REPLICATE, N_TEST_REPLICATES
import models as M


MIN_POOLED_EPISODES = 20
FORBIDDEN_ENDPOINT_FILES = {
    "policy_summary.csv",
    "budget_curve.csv",
    "null_draws.csv",
    "utility_permutation_null.csv",
    "information_contrast_null.csv",
    "construct_validity.json",
    "confirmatory_decision.json",
}


def run_pilot(
    run_root: Path,
    seeds: list[int],
    models: list[str],
    nested_reference_run: Path | None = None,
) -> dict:
    checks: list[dict] = []
    rows: list[dict] = []
    for forbidden in sorted(FORBIDDEN_ENDPOINT_FILES):
        checks.append(
            {
                "id": f"endpoint_file_absent_{forbidden}",
                "pass": not (run_root / "metrics" / forbidden).exists(),
            }
        )
    for seed in seeds:
        master = run_root / "data" / f"telemetry_seed{seed}.npz"
        with np.load(master) as dataset:
            checks.extend(
                [
                    {
                        "id": f"schema_seed{seed}",
                        "pass": int(dataset["schema_version"]) == 5,
                    },
                    {
                        "id": f"replicate_count_seed{seed}",
                        "pass": int(dataset["n_test_replicates"])
                        == N_TEST_REPLICATES,
                    },
                ]
            )
            for replicate in range(N_TEST_REPLICATES):
                events = json.loads(str(dataset[f"ev_te_r{replicate}"]))
                valid_ids = all(
                    int(event["replicate"]) == replicate
                    and int(event["local_event_id"]) == local_id
                    and int(event["event_id"])
                    == replicate * EVENTS_PER_REPLICATE + local_id
                    for local_id, event in enumerate(events)
                )
                checks.append(
                    {
                        "id": f"event_namespace_seed{seed}_r{replicate}",
                        "pass": len(events) == EVENTS_PER_REPLICATE and valid_ids,
                    }
                )
        for model in models:
            payload = json.loads(
                (run_root / "raw" / f"model_seed{seed}_{model}.json").read_text(
                    encoding="utf-8"
                )
            )
            counts = [int(value) for value in payload["per_replicate_episode_count"]]
            thresholds = []
            for replicate in range(N_TEST_REPLICATES):
                rep_payload = json.loads(
                    (
                        run_root
                        / "replicates"
                        / f"r{replicate}"
                        / "raw"
                        / f"model_seed{seed}_{model}.json"
                    ).read_text(encoding="utf-8")
                )
                thresholds.append(float(rep_payload["threshold"]))
            episodes = payload["episodes"]
            namespace_valid = all(
                row["episode_uid"]
                == f"s{seed}:r{int(row['replicate'])}:e{int(row['local_episode_id'])}"
                and all(
                    int(row["replicate"]) * EVENTS_PER_REPLICATE
                    <= int(event_id)
                    < (int(row["replicate"]) + 1) * EVENTS_PER_REPLICATE
                    for event_id in row["event_ids"]
                )
                for row in episodes
            )
            checks.extend(
                [
                    {
                        "id": f"pooled_minimum_seed{seed}_{model}",
                        "pass": len(episodes) >= MIN_POOLED_EPISODES,
                        "value": len(episodes),
                        "minimum": MIN_POOLED_EPISODES,
                    },
                    {
                        "id": f"shared_threshold_seed{seed}_{model}",
                        "pass": bool(
                            np.allclose(
                                thresholds, thresholds[0], rtol=0.0, atol=1e-12
                            )
                        ),
                    },
                    {
                        "id": f"episode_namespace_seed{seed}_{model}",
                        "pass": namespace_valid,
                    },
                    {
                        "id": f"no_raw_trajectory_concatenation_seed{seed}_{model}",
                        "pass": payload.get("raw_trajectory_concatenation") is False,
                    },
                ]
            )
            rows.append(
                {
                    "seed": seed,
                    "model": model,
                    "pooled_episode_count": len(episodes),
                    "per_replicate_episode_count": counts,
                    "threshold": thresholds[0],
                    "runtime_seconds": float(payload["runtime_seconds"]),
                }
            )
            if nested_reference_run is not None:
                reference = json.loads(
                    (
                        nested_reference_run
                        / "raw"
                        / f"model_seed{seed}_{model}.json"
                    ).read_text(encoding="utf-8")
                )
                checks.append(
                    {
                        "id": f"r3_byte_nested_episode_counts_seed{seed}_{model}",
                        "pass": counts[:3]
                        == [
                            int(value)
                            for value in reference["per_replicate_episode_count"]
                        ],
                    }
                )
    failed = [row["id"] for row in checks if not row["pass"]]
    return {
        "schema_version": 5,
        "status": "PASS" if not failed else "FAIL",
        "endpoint_blind": True,
        "policy_scores_computed": False,
        "utility_or_null_endpoints_computed": False,
        "seeds": seeds,
        "models": models,
        "minimum_pooled_episodes": MIN_POOLED_EPISODES,
        "n_test_replicates": N_TEST_REPLICATES,
        "nested_r3_reference": str(nested_reference_run)
        if nested_reference_run is not None
        else None,
        "n_checks": len(checks),
        "failed": failed,
        "episode_count_rows": rows,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--models", default=",".join(M.MODELS))
    parser.add_argument("--nested-reference-run", type=Path)
    args = parser.parse_args()
    seeds = parse_seed_spec(args.seeds)
    models = [value.strip() for value in args.models.split(",") if value.strip()]
    if any(model not in M.MODELS for model in models):
        raise ValueError("unknown model in --models")
    result = run_pilot(args.run_root, seeds, models, args.nested_reference_run)
    output = args.run_root / "metrics" / "property_pilot_v5.json"
    write_json(output, result)
    print(
        f"CRITICALITY_V5_PILOT_{result['status']} checks={result['n_checks']} "
        f"failed={len(result['failed'])}"
    )
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Full pre-endpoint property gate for the replicate-pooled V5 construct.

Operation: f07-prospective-confirmation-v5-20260828
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import label_binarize

import criticality_analysis_v4 as v4
from criticality_generator_v5 import EVENTS_PER_REPLICATE, N_TEST_REPLICATES
import models as M


ANALYSIS_SCHEMA_VERSION = 5
MIN_POOLED_EPISODES = 20


def _strict_float_embedding(original: np.ndarray, transformed: np.ndarray) -> bool:
    """Return true when a mathematical transform stayed injective in float64."""

    unique, first = np.unique(np.asarray(original, dtype=float), return_index=True)
    mapped = np.asarray(transformed, dtype=float)[first]
    order = np.argsort(unique, kind="stable")
    return bool(np.all(np.diff(mapped[order]) > 0))


def load_events_v5(run_root: Path, seed: int) -> list[dict]:
    path = run_root / "data" / f"telemetry_seed{seed}.npz"
    with np.load(path) as dataset:
        return [
            event
            for replicate in range(N_TEST_REPLICATES)
            for event in json.loads(str(dataset[f"ev_te_r{replicate}"]))
        ]


def property_tests(run_root: Path, seeds: list[int], models: list[str]) -> dict:
    checks: list[dict] = []
    pooled_events: list[dict] = []
    event_seed: list[int] = []
    amplitude_scales: dict[str, float] = {}
    raw_checks_pass = True
    for seed in seeds:
        path = run_root / "data" / f"telemetry_seed{seed}.npz"
        with np.load(path) as dataset:
            amplitude = float(dataset["amplitude_scale"])
            amplitude_scales[str(seed)] = amplitude
            checks.extend(
                [
                    {
                        "id": f"amplitude_scale_seed{seed}",
                        "pass": bool(np.isclose(amplitude, 1.0, rtol=0, atol=1e-12)),
                        "value": amplitude,
                        "expected": 1.0,
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
                difference = np.abs(
                    dataset[f"Xte_r{replicate}"]
                    - dataset[f"Xte_nominal_r{replicate}"]
                ) / np.maximum(dataset["train_sigma"][None, :], 1e-9)
                namespace_valid = len(events) == EVENTS_PER_REPLICATE
                for local_id, event in enumerate(events):
                    recomputed = difference[event["start"] : event["end"]].mean(
                        axis=0
                    )
                    stored = np.asarray(event["impact_by_channel"], dtype=float)
                    affected = {int(event["ch"])}
                    if int(event["sec"]) >= 0:
                        affected.add(int(event["sec"]))
                    unaffected = sorted(set(range(12)) - affected)
                    valid = (
                        np.allclose(recomputed, stored, rtol=1e-6, atol=1e-7)
                        and all(recomputed[channel] > 0 for channel in affected)
                        and np.allclose(recomputed[unaffected], 0.0, atol=1e-7)
                    )
                    raw_checks_pass = raw_checks_pass and bool(valid)
                    namespace_valid = namespace_valid and (
                        int(event["replicate"]) == replicate
                        and int(event["local_event_id"]) == local_id
                        and int(event["event_id"])
                        == replicate * EVENTS_PER_REPLICATE + local_id
                    )
                checks.append(
                    {
                        "id": f"event_namespace_seed{seed}_r{replicate}",
                        "pass": bool(namespace_valid),
                    }
                )
                pooled_events.extend(events)
                event_seed.extend([seed] * len(events))
    checks.append({"id": "raw_counterfactual_channel_impact", "pass": raw_checks_pass})

    impacts = np.asarray([event["impact"] for event in pooled_events], dtype=float)
    types = np.asarray([event["type"] for event in pooled_events])
    seeds_array = np.asarray(event_seed)
    type_auc: dict[str, float] = {}
    for fault_type in sorted(set(types)):
        auc = float(roc_auc_score(types == fault_type, impacts))
        directionless = max(auc, 1.0 - auc)
        type_auc[fault_type] = directionless
        checks.append(
            {
                "id": f"type_impact_auc_{fault_type}",
                "pass": directionless <= v4.TYPE_ONE_VS_REST_AUC_MAX,
                "value": directionless,
                "maximum": v4.TYPE_ONE_VS_REST_AUC_MAX,
            }
        )
    classes = sorted(set(types))
    probabilities = np.zeros((len(types), len(classes)), dtype=float)
    for held_seed in seeds:
        train = seeds_array != held_seed
        test = ~train
        classifier = LogisticRegression(max_iter=2000).fit(
            np.log(impacts[train])[:, None], types[train]
        )
        local = classifier.predict_proba(np.log(impacts[test])[:, None])
        for local_id, class_name in enumerate(classifier.classes_):
            probabilities[test, classes.index(class_name)] = local[:, local_id]
    binary = label_binarize(types, classes=classes)
    multiclass_auc = float(
        roc_auc_score(binary, probabilities, average="macro", multi_class="ovr")
    )
    checks.append(
        {
            "id": "leave_one_seed_out_type_from_impact_auc",
            "pass": multiclass_auc <= v4.TYPE_MULTICLASS_AUC_MAX,
            "value": multiclass_auc,
            "maximum": v4.TYPE_MULTICLASS_AUC_MAX,
        }
    )
    utility_shares: dict[str, dict[str, float]] = {}
    for scenario, vector in v4.SCENARIOS.items():
        utilities = v4.event_utilities(pooled_events, vector)
        utility_shares[scenario] = {}
        for fault_type in classes:
            share = float(utilities[types == fault_type].sum() / utilities.sum())
            utility_shares[scenario][fault_type] = share
            checks.append(
                {
                    "id": f"type_utility_share_{scenario}_{fault_type}",
                    "pass": share <= v4.TYPE_UTILITY_SHARE_MAX,
                    "value": share,
                    "maximum": v4.TYPE_UTILITY_SHARE_MAX,
                }
            )

    reordered = []
    episode_counts: list[dict] = []
    for seed in seeds:
        events = load_events_v5(run_root, seed)
        for model in models:
            payload = v4.load_payload(run_root, seed, model)
            episodes = payload["episodes"]
            counts = [int(value) for value in payload["per_replicate_episode_count"]]
            episode_counts.append(
                {
                    "seed": seed,
                    "model": model,
                    "pooled": len(episodes),
                    "per_replicate": counts,
                }
            )
            checks.append(
                {
                    "id": f"minimum_pooled_episode_count_seed{seed}_{model}",
                    "pass": len(episodes) >= MIN_POOLED_EPISODES,
                    "value": len(episodes),
                    "minimum": MIN_POOLED_EPISODES,
                }
            )
            namespace_valid = all(
                int(row["replicate"]) * EVENTS_PER_REPLICATE
                <= int(event_id)
                < (int(row["replicate"]) + 1) * EVENTS_PER_REPLICATE
                for row in episodes
                for event_id in row["event_ids"]
            )
            checks.append(
                {
                    "id": f"cross_replicate_matching_forbidden_seed{seed}_{model}",
                    "pass": namespace_valid,
                }
            )
            checks.append(
                {
                    "id": f"generated_episode_at_most_one_event_seed{seed}_{model}",
                    "pass": all(len(row["event_ids"]) <= 1 for row in episodes),
                }
            )
            tie_mass = v4.tied_pair_mass(v4.score_magnitude(episodes))
            checks.append(
                {
                    "id": f"tie_pair_mass_seed{seed}_{model}",
                    "pass": tie_mass <= v4.TIE_PAIR_MASS_MAX
                    if model in v4.PRIMARY_CONFIRMATORY_MODELS
                    else True,
                    "value": tie_mass,
                    "maximum": v4.TIE_PAIR_MASS_MAX,
                }
            )
            for mass_key in ("native_mass", "occlusion_mass"):
                masses = np.asarray([row[mass_key] for row in episodes], dtype=float)
                valid = (
                    masses.shape == (len(episodes), 12)
                    and np.all(np.isfinite(masses))
                    and np.all(masses >= 0)
                    and np.allclose(masses.sum(axis=1), 1.0, atol=1e-9)
                )
                checks.append(
                    {
                        "id": f"mass_complete_seed{seed}_{model}_{mass_key}",
                        "pass": bool(valid),
                    }
                )
            degenerate_rate = float(
                np.mean(
                    [
                        row["native_degenerate"] or row["occlusion_degenerate"]
                        for row in episodes
                    ]
                )
            )
            checks.append(
                {
                    "id": f"degenerate_rate_seed{seed}_{model}",
                    "pass": degenerate_rate <= v4.DEGENERATE_RATE_MAX,
                    "value": degenerate_rate,
                    "maximum": v4.DEGENERATE_RATE_MAX,
                }
            )
            for replicate in range(N_TEST_REPLICATES):
                root = run_root / "replicates" / f"r{replicate}"
                rep_payload = v4.load_payload(root, seed, model)
                rep_episodes = rep_payload["episodes"]
                with np.load(
                    root / "ckpt" / f"model_seed{seed}_{model}.npz"
                ) as artifact:
                    peak = artifact["episode_peak"]
                    mean_test = artifact["mean_test"]
                    mean_val = artifact["mean_val"]
                    original = v4.tail_surprisal(mean_test[peak], mean_val)
                    transforms = (
                        ("scale2", mean_test * 2.0, mean_val * 2.0),
                        ("affine", mean_test * 3.7 + 2.0, mean_val * 3.7 + 2.0),
                        ("cube", mean_test**3, mean_val**3),
                        ("log1p", np.log1p(mean_test), np.log1p(mean_val)),
                    )
                    testable = [
                        (label, test_values, val_values)
                        for label, test_values, val_values in transforms
                        if _strict_float_embedding(mean_test, test_values)
                        and _strict_float_embedding(mean_val, val_values)
                    ]
                    invariant = bool(testable) and all(
                        np.allclose(
                            original,
                            v4.tail_surprisal(test_values[peak], val_values),
                        )
                        for _, test_values, val_values in testable
                    )
                    native = v4._recompute_aggregated_mass(
                        artifact["raw_window_native"],
                        rep_episodes,
                        artifact["window_tail_weights"],
                    )
                    occlusion = v4._recompute_aggregated_mass(
                        artifact["raw_window_occlusion"],
                        rep_episodes,
                        artifact["window_tail_weights"],
                    )
                    aggregation_valid = np.allclose(
                        native, artifact["episode_native_mass"], atol=1e-10
                    ) and np.allclose(
                        occlusion,
                        artifact["episode_occlusion_mass"],
                        atol=1e-10,
                    )
                checks.extend(
                    [
                        {
                            "id": f"monotone_invariance_seed{seed}_{model}_r{replicate}",
                            "pass": bool(invariant),
                            "tested_transformations": [
                                label for label, _, _ in testable
                            ],
                            "excluded_noninjective_float_transformations": [
                                label
                                for label, _, _ in transforms
                                if label not in {value[0] for value in testable}
                            ],
                        },
                        {
                            "id": f"episode_aggregation_seed{seed}_{model}_r{replicate}",
                            "pass": bool(aggregation_valid),
                        },
                    ]
                )
            uniform = v4.policy_scores(episodes, events, v4.SCENARIOS["uniform"])
            checks.append(
                {
                    "id": f"uniform_identity_seed{seed}_{model}",
                    "pass": bool(
                        np.allclose(
                            uniform["score_only"],
                            uniform["native_explanation_context"],
                        )
                        and np.allclose(
                            uniform["score_only"], uniform["occlusion_context"]
                        )
                    ),
                }
            )
            for scenario in v4.NONUNIFORM_SCENARIOS:
                values = v4.policy_scores(episodes, events, v4.SCENARIOS[scenario])
                tau = float(
                    kendalltau(
                        values["score_only"], values["occlusion_context"]
                    ).statistic
                )
                reordered.append(tau < 0.999999)
                utilities = v4.event_utilities(events, v4.SCENARIOS[scenario])
                upper, _ = v4.attainable_upper_bound(episodes, utilities)
                maximum_policy = max(
                    v4.evaluate_policy(
                        values[policy],
                        episodes,
                        utilities,
                        v4.BOOTSTRAP_SEED
                        + seed * 100
                        + list(M.MODELS).index(model),
                    )[0]
                    for policy in v4.POLICIES
                )
                checks.append(
                    {
                        "id": f"upper_bound_dominance_seed{seed}_{model}_{scenario}",
                        "pass": maximum_policy <= upper + 1e-10,
                        "upper": upper,
                        "maximum_policy": maximum_policy,
                    }
                )
    reordered_fraction = float(np.mean(reordered)) if reordered else 0.0
    checks.append(
        {
            "id": "context_reordering_leverage",
            "pass": reordered_fraction >= v4.REORDERED_CELL_FRACTION_MIN,
            "value": reordered_fraction,
            "minimum": v4.REORDERED_CELL_FRACTION_MIN,
        }
    )
    duplicate = v4.matched_budget_metrics(
        np.asarray([0, 1, 2]), [[0], [0], [1]], np.asarray([10.0, 5.0]), 2
    )
    merged = v4.matched_budget_metrics(
        np.asarray([0]), [[0, 1]], np.asarray([10.0, 5.0]), 1
    )
    checks.extend(
        [
            {
                "id": "duplicate_alarm_no_double_credit",
                "pass": bool(np.isclose(duplicate["captured_utility"], 10.0)),
            },
            {
                "id": "merged_alarm_one_event_credit",
                "pass": bool(np.isclose(merged["captured_utility"], 10.0)),
            },
        ]
    )
    failed = [check["id"] for check in checks if not check["pass"]]
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "status": "PASS" if not failed else "FAIL",
        "n_checks": len(checks),
        "failed": failed,
        "generator_seeds": seeds,
        "model_seeds": seeds,
        "models": models,
        "primary_confirmatory_models": list(v4.PRIMARY_CONFIRMATORY_MODELS),
        "expected_amplitude_scale": 1.0,
        "amplitude_scales": amplitude_scales,
        "n_test_replicates": N_TEST_REPLICATES,
        "minimum_pooled_episodes": MIN_POOLED_EPISODES,
        "episode_counts": episode_counts,
        "type_impact_auc": type_auc,
        "multiclass_type_from_impact_auc": multiclass_auc,
        "type_utility_shares": utility_shares,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--models", default=",".join(M.MODELS))
    args = parser.parse_args()
    seeds = v4.parse_seed_spec(args.seeds)
    models = [value.strip() for value in args.models.split(",") if value.strip()]
    result = property_tests(args.run_root, seeds, models)
    v4.write_json(args.run_root / "metrics" / "property_tests.json", result)
    print(
        f"CRITICALITY_V5_PROPERTY_{result['status']} checks={result['n_checks']} "
        f"failed={len(result['failed'])}"
    )
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

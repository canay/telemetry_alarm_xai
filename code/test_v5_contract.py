"""Contract tests for the prospective V5 exposure design.

Operation: f07-prospective-confirmation-v5-20260828
"""

from __future__ import annotations

import json

import numpy as np

from criticality_analysis_v5 import (
    evaluate_policy_singleton_fast,
    matched_budget_metrics_fast,
    within_replicate_type_permutation,
)
from criticality_analysis_v4 import evaluate_policy, matched_budget_metrics
from criticality_generator import generate_seed_v2
from criticality_generator_v5 import generate_seed_v5
from criticality_property_v5 import _strict_float_embedding
from confirmatory_analysis_v5 import PRIMARY_MODELS, SEEDS, decisions, pooled_endpoints
from power_freeze_v5 import joint_pass_rate


def test_v5_replicate_zero_preserves_v4_streams(tmp_path):
    v4_path = tmp_path / "v4.npz"
    v5_path = tmp_path / "v5.npz"
    generate_seed_v2(123, v4_path)
    generate_seed_v5(123, v5_path)
    with np.load(v4_path) as old, np.load(v5_path) as new:
        for shared in ("Xtr", "Xval", "Xtl", "ytl", "train_sigma"):
            assert np.array_equal(old[shared], new[shared])
        assert np.array_equal(old["Xte"], new["Xte_r0"])
        assert np.array_equal(old["yte"], new["yte_r0"])
        assert np.array_equal(old["Xte_nominal"], new["Xte_nominal_r0"])
        old_events = json.loads(str(old["ev_te"]))
        new_events = json.loads(str(new["ev_te_r0"]))
        for old_event, new_event in zip(old_events, new_events):
            stripped = {
                key: value
                for key, value in new_event.items()
                if key not in {"replicate", "local_event_id", "event_id"}
            }
            assert old_event == stripped


def test_v5_test_replicates_are_distinct_and_namespaced(tmp_path):
    path = tmp_path / "v5.npz"
    generate_seed_v5(124, path)
    with np.load(path) as dataset:
        assert not np.array_equal(dataset["Xte_r0"], dataset["Xte_r1"])
        assert not np.array_equal(dataset["Xte_r1"], dataset["Xte_r2"])
        for replicate in range(7):
            events = json.loads(str(dataset[f"ev_te_r{replicate}"]))
            assert len(events) == 36
            assert [event["event_id"] for event in events] == list(
                range(36 * replicate, 36 * (replicate + 1))
            )


def test_utility_permutation_never_crosses_replicate_or_type():
    events = [
        {"replicate": replicate, "type": fault_type}
        for replicate in range(3)
        for fault_type in ("a", "b")
        for _ in range(4)
    ]
    utilities = np.arange(len(events), dtype=float)
    permuted = within_replicate_type_permutation(
        utilities, events, np.random.default_rng(42)
    )
    for replicate in range(3):
        for fault_type in ("a", "b"):
            ids = [
                idx
                for idx, event in enumerate(events)
                if event["replicate"] == replicate and event["type"] == fault_type
            ]
            assert sorted(permuted[ids]) == sorted(utilities[ids])


def test_float_embedding_rejects_rounding_induced_ties():
    original = np.asarray([0.9999999999999997, 0.9999999999999999, 1.0])
    assert _strict_float_embedding(original, original * 2.0)
    assert not _strict_float_embedding(original, original * 3.7 + 2.0)


def test_induced_subgraph_matching_is_exact():
    rng = np.random.default_rng(9841)
    for _ in range(100):
        n_events = int(rng.integers(5, 40))
        n_episodes = int(rng.integers(5, 50))
        event_ids = [
            sorted(
                set(
                    int(value)
                    for value in rng.integers(
                        0, n_events, size=int(rng.integers(0, 4))
                    )
                )
            )
            for _ in range(n_episodes)
        ]
        utilities = rng.uniform(0.1, 10.0, size=n_events)
        ordering = rng.permutation(n_episodes)
        budget = int(rng.integers(0, n_episodes + 1))
        expected = matched_budget_metrics(
            ordering, event_ids, utilities, budget
        )
        observed = matched_budget_metrics_fast(
            ordering, event_ids, utilities, budget
        )
        for key in expected:
            assert np.isclose(expected[key], observed[key], rtol=0.0, atol=1e-12)


def test_vectorized_singleton_policy_is_exact_with_ties():
    rng = np.random.default_rng(728)
    for _ in range(25):
        n_events = int(rng.integers(20, 80))
        n_episodes = int(rng.integers(40, 160))
        episodes = [
            {
                "event_ids": []
                if rng.random() < 0.25
                else [int(rng.integers(0, n_events))]
            }
            for _ in range(n_episodes)
        ]
        values = np.round(rng.normal(size=n_episodes), 1)
        utilities = rng.uniform(0.1, 20.0, size=n_events)
        expected = evaluate_policy(
            values, episodes, utilities, 1993, include_details=False
        )[0]
        observed = evaluate_policy_singleton_fast(
            values, episodes, utilities, 1993, {}
        )[0]
        assert np.isclose(expected, observed, rtol=0.0, atol=1e-12)


def test_vectorized_joint_power_matches_frozen_scalar_decisions():
    rng = np.random.default_rng(20_260_830)
    samples = rng.normal(
        loc=np.asarray([0.5, 0.6, 0.4, 0.3]),
        scale=np.asarray([0.4, 0.5, 0.3, 0.2]),
        size=(37, 20, 4),
    )
    observed = joint_pass_rate(samples)
    passes = []
    for sample in samples:
        rows = [
            {
                "platform_raw": row[0],
                "payload_harm_raw": row[1],
                "scenario_contrast_raw": row[0] + row[1],
                "platform_information": row[2],
                "payload_information": row[3],
            }
            for row in sample
        ]
        passes.append(all(result["pass"] for result in decisions(rows).values()))
    assert observed == np.mean(passes)


def test_primary_pool_applies_payload_harm_and_information_signs():
    policy = {}
    utility_null = {}
    for offset, seed in enumerate(SEEDS):
        for model in PRIMARY_MODELS:
            policy[(seed, model, "platform_survival", "score_only")] = 1.0
            policy[(seed, model, "platform_survival", "occlusion_context")] = (
                1.5 + 0.01 * offset
            )
            policy[(seed, model, "payload_first", "score_only")] = 1.0
            policy[(seed, model, "payload_first", "occlusion_context")] = (
                0.6 - 0.01 * offset
            )
            utility_null[(seed, model, "platform_survival")] = 0.1
            utility_null[(seed, model, "payload_first")] = -0.6
    rows = pooled_endpoints(policy, utility_null, PRIMARY_MODELS)
    assert len(rows) == len(SEEDS)
    for offset, row in enumerate(rows):
        assert np.isclose(row["platform_raw"], 0.5 + 0.01 * offset)
        assert np.isclose(row["payload_harm_raw"], 0.4 + 0.01 * offset)
        assert np.isclose(row["scenario_contrast_raw"], 0.9 + 0.02 * offset)
        assert np.isclose(row["platform_information"], 0.4 + 0.01 * offset)
        assert np.isclose(row["payload_information"], 0.2 - 0.01 * offset)

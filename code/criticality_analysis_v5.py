"""Replicate-aware V5 analysis built on the frozen V4 estimand machinery.

The primary estimand pools episode records after within-trajectory episode
formation.  Utility permutations are restricted jointly by test replicate and
fault type.  A mandatory sensitivity averages separately evaluated replicate
queues within each inferential seed.

Operation: f07-prospective-confirmation-v5-20260828
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linear_sum_assignment

import criticality_analysis_v4 as v4
from criticality_generator_v5 import EVENTS_PER_REPLICATE, N_TEST_REPLICATES
from criticality_property_v5 import load_events_v5
import models as M


MIN_POOLED_EPISODES = 20
ANALYSIS_SCHEMA_VERSION = 5


def evaluate_policy_singleton_fast(
    values: np.ndarray,
    episodes: list[dict],
    utilities: np.ndarray,
    tie_seed: int,
    cache: dict,
) -> tuple[float, list[dict]]:
    """Vectorized V4 MUC--AUC for generated episodes with <=1 event each."""

    event_by_episode = np.asarray(
        [int(row["event_ids"][0]) if row["event_ids"] else -1 for row in episodes],
        dtype=np.int64,
    )
    values_array = np.asarray(values, dtype=float)
    key = (
        hashlib.sha256(values_array.tobytes()).digest(),
        int(tie_seed),
        hashlib.sha256(event_by_episode.tobytes()).digest(),
        len(utilities),
    )
    prepared = cache.get(key)
    if prepared is None:
        orderings = np.asarray(v4.tie_orderings(values_array, tie_seed), dtype=np.int64)
        n = len(episodes)
        realized_to_budget = {
            min(n, max(1, int(np.floor(fraction * n)))) / n: min(
                n, max(1, int(np.floor(fraction * n)))
            )
            for fraction in v4.FRACTION_BUDGETS
        }
        realized_to_budget[v4.PRIMARY_MAX_LOAD] = realized_to_budget[
            max(realized_to_budget)
        ]
        x = np.asarray([0.0, *sorted(realized_to_budget)], dtype=float)
        selectors = []
        for realized in x[1:]:
            budget = realized_to_budget[float(realized)]
            selected_events = event_by_episode[orderings[:, :budget]]
            mask = np.zeros((len(orderings), len(utilities)), dtype=float)
            for draw, event_ids in enumerate(selected_events):
                valid = np.unique(event_ids[event_ids >= 0])
                mask[draw, valid] = 1.0
            selectors.append(mask)
        prepared = (x, selectors)
        if len(orderings) > 1:
            cache[key] = prepared
    x, selectors = prepared
    total = float(np.asarray(utilities, dtype=float).sum())
    captures = [
        selector @ np.asarray(utilities, dtype=float) / total
        if total > 0
        else np.zeros(selector.shape[0], dtype=float)
        for selector in selectors
    ]
    y = np.column_stack([np.zeros(len(captures[0])), *captures])
    aucs = np.trapezoid(y, x, axis=1) / v4.PRIMARY_MAX_LOAD
    return float(np.mean(aucs)), []


def matched_budget_metrics_fast(
    ordering: np.ndarray,
    episode_event_ids: list[list[int]],
    utilities: np.ndarray,
    budget: int,
) -> dict[str, float]:
    """Exact V4 matching on the induced event subgraph only.

    V4 allocates one column for every generated event even when the selected
    alarms cannot overlap most of them.  Removing all-zero columns leaves the
    assignment problem and every metric unchanged while making the R=7 null
    loops tractable.
    """

    budget = min(max(int(budget), 0), len(ordering))
    total = float(utilities.sum())
    if budget == 0 or not len(utilities):
        return {
            "capture": 0.0,
            "captured_utility": 0.0,
            "matched_events": 0.0,
            "event_coverage": 0.0,
            "false_duplicate_review_fraction": 0.0,
        }
    selected = [int(value) for value in ordering[:budget]]
    adjacency = [
        sorted(set(int(value) for value in episode_event_ids[episode_id]))
        for episode_id in selected
    ]
    if all(len(events) <= 1 for events in adjacency):
        unique_events = {
            events[0] for events in adjacency if events
        }
        captured = float(sum(float(utilities[event_id]) for event_id in unique_events))
        matched = len(unique_events)
        return {
            "capture": captured / total if total > 0 else 0.0,
            "captured_utility": captured,
            "matched_events": float(matched),
            "event_coverage": matched / len(utilities),
            "false_duplicate_review_fraction": 1.0 - matched / budget,
        }
    event_to_rows: dict[int, list[int]] = {}
    for row_id, events in enumerate(adjacency):
        for event_id in events:
            event_to_rows.setdefault(event_id, []).append(row_id)
    if not event_to_rows:
        return {
            "capture": 0.0,
            "captured_utility": 0.0,
            "matched_events": 0.0,
            "event_coverage": 0.0,
            "false_duplicate_review_fraction": 1.0,
        }
    unseen_rows = {row_id for row_id, events in enumerate(adjacency) if events}
    captured_values: list[float] = []
    while unseen_rows:
        start = unseen_rows.pop()
        component_rows = {start}
        component_events: set[int] = set()
        row_frontier = [start]
        while row_frontier:
            row_id = row_frontier.pop()
            for event_id in adjacency[row_id]:
                if event_id in component_events:
                    continue
                component_events.add(event_id)
                for neighbor in event_to_rows[event_id]:
                    if neighbor not in component_rows:
                        component_rows.add(neighbor)
                        unseen_rows.discard(neighbor)
                        row_frontier.append(neighbor)
        rows = sorted(component_rows)
        events = sorted(component_events)
        if len(events) == 1:
            captured_values.append(float(utilities[events[0]]))
            continue
        if len(rows) == 1:
            captured_values.append(float(max(utilities[event_id] for event_id in events)))
            continue
        lookup = {event_id: column for column, event_id in enumerate(events)}
        weights = np.zeros((len(rows), len(events)), dtype=float)
        for local_row, row_id in enumerate(rows):
            for event_id in adjacency[row_id]:
                weights[local_row, lookup[event_id]] = utilities[event_id]
        row_ids, columns = linear_sum_assignment(-weights)
        selected_weights = weights[row_ids, columns]
        captured_values.extend(float(value) for value in selected_weights if value > 0)
    captured = float(sum(captured_values))
    matched = len(captured_values)
    return {
        "capture": captured / total if total > 0 else 0.0,
        "captured_utility": captured,
        "matched_events": float(matched),
        "event_coverage": matched / len(utilities),
        "false_duplicate_review_fraction": 1.0 - matched / budget,
    }


def within_replicate_type_permutation(
    utilities: np.ndarray, events: list[dict], rng: np.random.Generator
) -> np.ndarray:
    result = utilities.copy()
    strata = sorted({(int(event["replicate"]), event["type"]) for event in events})
    for replicate, fault_type in strata:
        ids = np.asarray(
            [
                idx
                for idx, event in enumerate(events)
                if int(event["replicate"]) == replicate
                and event["type"] == fault_type
            ]
        )
        result[ids] = rng.permutation(result[ids])
    return result


def _replicate_view(
    episodes: list[dict], events: list[dict], replicate: int
) -> tuple[list[dict], list[dict]]:
    offset = replicate * EVENTS_PER_REPLICATE
    local_events = events[offset : offset + EVENTS_PER_REPLICATE]
    local_episodes = []
    for row in episodes:
        if int(row["replicate"]) != replicate:
            continue
        transformed = dict(row)
        transformed["event_ids"] = [int(value) - offset for value in row["event_ids"]]
        local_episodes.append(transformed)
    return local_episodes, local_events


def write_replicate_sensitivity(
    run_root: Path, seeds: list[int], null_draws: int
) -> list[dict]:
    rows: list[dict] = []
    for seed in seeds:
        events = load_events_v5(run_root, seed)
        for model in M.MODELS:
            payload = v4.load_payload(run_root, seed, model)
            for replicate in range(N_TEST_REPLICATES):
                episodes, local_events = _replicate_view(
                    payload["episodes"], events, replicate
                )
                for scenario_id, scenario in enumerate(v4.NONUNIFORM_SCENARIOS):
                    criticality = v4.SCENARIOS[scenario]
                    utilities = v4.event_utilities(local_events, criticality)
                    scores = v4.policy_scores(episodes, local_events, criticality)
                    tie_seed = int(
                        np.random.SeedSequence(
                            [seed, list(M.MODELS).index(model), replicate, scenario_id, 601]
                        ).generate_state(1, dtype=np.uint32)[0]
                    )
                    baseline, _ = v4.evaluate_policy(
                        scores["score_only"], episodes, utilities, tie_seed
                    )
                    occlusion, _ = v4.evaluate_policy(
                        scores["occlusion_context"], episodes, utilities, tie_seed
                    )
                    null_gains = []
                    for draw in range(null_draws):
                        rng = np.random.default_rng(
                            np.random.SeedSequence(
                                [
                                    seed,
                                    list(M.MODELS).index(model),
                                    replicate,
                                    scenario_id,
                                    draw,
                                    809,
                                ]
                            )
                        )
                        permuted = v4._within_type_permutation(
                            utilities, local_events, rng
                        )
                        baseline_null, _ = v4.evaluate_policy(
                            scores["score_only"],
                            episodes,
                            permuted,
                            tie_seed,
                            include_details=False,
                        )
                        occlusion_null, _ = v4.evaluate_policy(
                            scores["occlusion_context"],
                            episodes,
                            permuted,
                            tie_seed,
                            include_details=False,
                        )
                        null_gains.append(occlusion_null - baseline_null)
                    raw_gain = occlusion - baseline
                    rows.append(
                        {
                            "seed": seed,
                            "model": model,
                            "replicate": replicate,
                            "scenario": scenario,
                            "n_episodes": len(episodes),
                            "score_only_muc_auc_0_40": baseline,
                            "occlusion_context_muc_auc_0_40": occlusion,
                            "raw_gain": raw_gain,
                            "mean_within_type_utility_null_gain": float(
                                np.mean(null_gains)
                            ),
                            "information_gain": raw_gain - float(np.mean(null_gains)),
                        }
                    )
    v4.write_csv(run_root / "metrics" / "per_replicate_sensitivity.csv", rows)
    return rows


def analyze(run_root: Path, seeds: list[int], null_draws: int) -> dict:
    original = {
        "schema": v4.ANALYSIS_SCHEMA_VERSION,
        "minimum": v4.MIN_EPISODES,
        "load_events": v4.load_events,
        "permutation": v4._within_type_permutation,
        "matching": v4.matched_budget_metrics,
        "evaluate": v4.evaluate_policy,
    }
    v4.ANALYSIS_SCHEMA_VERSION = ANALYSIS_SCHEMA_VERSION
    v4.MIN_EPISODES = MIN_POOLED_EPISODES
    v4.load_events = load_events_v5
    v4._within_type_permutation = within_replicate_type_permutation
    v4.matched_budget_metrics = matched_budget_metrics_fast
    last_heartbeat = time.monotonic()
    evaluation_calls = 0
    singleton_cache: dict = {}

    def evaluate_with_heartbeat(*args, **kwargs):
        nonlocal last_heartbeat, evaluation_calls
        include_details = kwargs.get("include_details", True)
        values, episodes, utilities, tie_seed = args[:4]
        if not include_details and all(
            len(row["event_ids"]) <= 1 for row in episodes
        ):
            result = evaluate_policy_singleton_fast(
                values, episodes, utilities, tie_seed, singleton_cache
            )
        else:
            result = original["evaluate"](*args, **kwargs)
        evaluation_calls += 1
        now = time.monotonic()
        if now - last_heartbeat >= 30.0:
            print(
                f"V5_ANALYSIS_HEARTBEAT evaluations={evaluation_calls} "
                f"elapsed_since_last={now - last_heartbeat:.1f}s",
                flush=True,
            )
            last_heartbeat = now
        return result

    v4.evaluate_policy = evaluate_with_heartbeat
    try:
        decision = v4.analyze(run_root, seeds, null_draws)
        sensitivity = write_replicate_sensitivity(run_root, seeds, null_draws)
    finally:
        v4.ANALYSIS_SCHEMA_VERSION = original["schema"]
        v4.MIN_EPISODES = original["minimum"]
        v4.load_events = original["load_events"]
        v4._within_type_permutation = original["permutation"]
        v4.matched_budget_metrics = original["matching"]
        v4.evaluate_policy = original["evaluate"]
    decision["analysis_schema_version"] = ANALYSIS_SCHEMA_VERSION
    decision["primary_estimand"] = (
        "pooled episode queue after within-replicate segmentation"
    )
    decision["utility_permutation_strata"] = "test_replicate_by_fault_type"
    decision["per_replicate_sensitivity_rows"] = len(sensitivity)
    legacy_flags = {
        key: decision["kill_switches"].pop(key)
        for key in (
            "no_positive_primary_omnibus_for_power",
            "no_positive_tie_eligible_sensitivity_for_power",
        )
    }
    decision["legacy_universal_uplift_diagnostics"] = {
        "status": "NOT_A_FROZEN_ENDPOINT",
        "reason": (
            "same-sign averaging across platform and payload scenarios is "
            "incompatible with the frozen directional heterogeneity rule"
        ),
        "six_model_same_sign_cross_scenario": decision.pop("primary_omnibus"),
        "five_model_same_sign_cross_scenario": decision.pop(
            "tie_eligible_sensitivity_omnibus"
        ),
        "six_model_native_same_sign_cross_scenario": decision.pop("native_omnibus"),
        "six_model_univariate_power_diagnostic": decision.pop("power_plan"),
        "five_model_univariate_power_diagnostic": decision.pop(
            "tie_eligible_power_plan"
        ),
        "diagnostic_flags": legacy_flags,
    }
    v4.write_json(run_root / "metrics" / "construct_validity.json", decision)
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--null-draws", type=int, default=200)
    args = parser.parse_args()
    seeds = v4.parse_seed_spec(args.seeds)
    decision = analyze(args.run_root, seeds, args.null_draws)
    print(json.dumps(v4._json_safe(decision), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

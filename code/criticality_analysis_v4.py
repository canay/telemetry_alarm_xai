"""Pre-registered V4 analysis for criticality-conditioned episode review.

V4 replaces the small-sample percentile-bootstrap decision with a one-sided
Student t lower bound, enforces the primary-model tie gate, and binds resumable
analysis checkpoints to the exact code and null-draw count.

Operation: f07-criticality-v4-pre-freeze-repair-20260826
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.stats import chi2, kendalltau, norm, t, ttest_1samp
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import label_binarize

from telemetry_generator import CH_NAMES
import models as M


ABSOLUTE_BUDGETS = (1, 3, 5, 10)
FRACTION_BUDGETS = (0.05, 0.10, 0.20, 0.40)
PRIMARY_MAX_LOAD = 0.40
TIE_DRAWS = 100
TIE_PAIR_MASS_MAX = 0.50
MIN_EPISODES = 10
DEGENERATE_RATE_MAX = 0.05
TYPE_ONE_VS_REST_AUC_MAX = 0.65
TYPE_MULTICLASS_AUC_MAX = 0.60
TYPE_UTILITY_SHARE_MAX = 0.25
REORDERED_CELL_FRACTION_MIN = 0.25
BOOTSTRAP_B = 10_000
BOOTSTRAP_SEED = 20_260_826
POWER_OUTER = 200
POWER_MAX_N = 300
ANALYSIS_SCHEMA_VERSION = 4
PRIMARY_CONFIRMATORY_MODELS = ("lr", "iforest", "hgb", "pca", "ae")

SCENARIOS = {
    "uniform": np.ones(12, dtype=float),
    # v_bus, i_load, i_sa, i_batt, t_batt, t_sa, t_pl, t_obc,
    # t_rad, w_rwx, w_rwy, t_rwx
    "platform_survival": np.asarray(
        [4, 2, 2, 4, 4, 2, 1, 4, 2, 4, 4, 4], dtype=float
    ),
    "payload_first": np.asarray(
        [2, 4, 1, 2, 2, 1, 4, 2, 1, 1, 1, 1], dtype=float
    ),
}
NONUNIFORM_SCENARIOS = ("platform_survival", "payload_first")
POLICIES = (
    "score_only",
    "channel_context_reference",
    "native_explanation_context",
    "occlusion_context",
)


def parse_seed_spec(specification: str) -> list[int]:
    seeds: list[int] = []
    for token in specification.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            first, last = (int(value) for value in token.split("-", 1))
            seeds.extend(range(first, last + 1))
        else:
            seeds.append(int(token))
    return sorted(set(seeds))


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_events(run_root: Path, seed: int) -> list[dict]:
    path = run_root / "data" / f"telemetry_seed{seed}.npz"
    if not path.exists():
        raise FileNotFoundError(path)
    with np.load(path) as dataset:
        return json.loads(str(dataset["ev_te"]))


def load_payload(run_root: Path, seed: int, model: str) -> dict:
    path = run_root / "raw" / f"model_seed{seed}_{model}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def tail_surprisal(query: np.ndarray, nominal_validation: np.ndarray) -> np.ndarray:
    query = np.asarray(query, dtype=float)
    reference = np.sort(np.asarray(nominal_validation, dtype=float))
    count_ge = len(reference) - np.searchsorted(reference, query, side="left")
    fractional = np.zeros(len(query), dtype=float)
    for bin_id in np.unique(count_ge):
        ids = np.where(count_ge == bin_id)[0]
        values = query[ids]
        order = np.argsort(-values, kind="stable")
        ranks = np.empty(len(ids), dtype=float)
        cursor = 0
        while cursor < len(order):
            stop = cursor + 1
            while stop < len(order) and values[order[stop]] == values[order[cursor]]:
                stop += 1
            average_rank = 0.5 * ((cursor + 1) + stop)
            ranks[order[cursor:stop]] = average_rank
            cursor = stop
        fractional[ids] = ranks / (len(ids) + 1.0)
    p_value = (count_ge + fractional + 1.0) / (len(reference) + 1.0)
    return -np.log(p_value)


def event_utilities(events: list[dict], criticality: np.ndarray) -> np.ndarray:
    return np.asarray(
        [np.asarray(event["impact_by_channel"], dtype=float) @ criticality for event in events],
        dtype=float,
    )


def score_magnitude(episodes: list[dict]) -> np.ndarray:
    values = np.asarray([row["score_tail_surprisal"] for row in episodes], dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("invalid nominal-validation tail surprisal")
    return values + 1e-12


def explanation_policy_scores(
    episodes: list[dict], criticality: np.ndarray, mass_key: str
) -> np.ndarray:
    masses = np.asarray([row[mass_key] for row in episodes], dtype=float)
    if masses.shape != (len(episodes), len(criticality)):
        raise ValueError(f"invalid attribution mass shape: {masses.shape}")
    factor = (masses @ criticality) / float(np.mean(criticality))
    return score_magnitude(episodes) * factor


def channel_context_reference_scores(
    episodes: list[dict], events: list[dict], criticality: np.ndarray
) -> np.ndarray:
    """Truth-channel context reference; not a detection/utility upper bound."""

    factors = np.ones(len(episodes), dtype=float)
    mean_criticality = float(np.mean(criticality))
    for episode_id, episode in enumerate(episodes):
        candidates = []
        for event_id in episode["event_ids"]:
            impact = np.asarray(events[event_id]["impact_by_channel"], dtype=float)
            denominator = float(impact.sum() * mean_criticality)
            if denominator > 0:
                candidates.append(float((impact @ criticality) / denominator))
        if candidates:
            factors[episode_id] = max(candidates)
    return score_magnitude(episodes) * factors


def policy_scores(
    episodes: list[dict], events: list[dict], criticality: np.ndarray
) -> dict[str, np.ndarray]:
    return {
        "score_only": score_magnitude(episodes),
        "channel_context_reference": channel_context_reference_scores(
            episodes, events, criticality
        ),
        "native_explanation_context": explanation_policy_scores(
            episodes, criticality, "native_mass"
        ),
        "occlusion_context": explanation_policy_scores(
            episodes, criticality, "occlusion_mass"
        ),
    }


def tied_pair_mass(values: np.ndarray) -> float:
    values = np.asarray(values)
    n = len(values)
    if n < 2:
        return 0.0
    _, counts = np.unique(values, return_counts=True)
    tied = sum(int(count * (count - 1) // 2) for count in counts)
    return tied / (n * (n - 1) / 2)


def tie_orderings(values: np.ndarray, seed: int, draws: int = TIE_DRAWS) -> list[np.ndarray]:
    values = np.asarray(values, dtype=float)
    if len(np.unique(values)) == len(values):
        return [np.argsort(-values, kind="stable")]
    rng = np.random.default_rng(seed)
    return [np.lexsort((rng.random(len(values)), -values)) for _ in range(draws)]


def matched_budget_metrics(
    ordering: np.ndarray,
    episode_event_ids: list[list[int]],
    utilities: np.ndarray,
    budget: int,
) -> dict[str, float]:
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
    selected = ordering[:budget]
    weights = np.zeros((budget, len(utilities)), dtype=float)
    for row_id, episode_id in enumerate(selected):
        for event_id in episode_event_ids[int(episode_id)]:
            weights[row_id, event_id] = utilities[event_id]
    row_ids, event_ids = linear_sum_assignment(-weights)
    selected_weights = weights[row_ids, event_ids]
    positive = selected_weights > 0
    captured = float(selected_weights[positive].sum())
    matched = int(positive.sum())
    return {
        "capture": captured / total if total > 0 else 0.0,
        "captured_utility": captured,
        "matched_events": float(matched),
        "event_coverage": matched / len(utilities),
        "false_duplicate_review_fraction": 1.0 - matched / budget,
    }


def _ordering_curve(
    ordering: np.ndarray, episodes: list[dict], utilities: np.ndarray
) -> tuple[float, list[dict]]:
    n = len(episodes)
    event_ids = [list(map(int, row["event_ids"])) for row in episodes]
    details: list[dict] = []
    for budget in ABSOLUTE_BUDGETS:
        actual = min(budget, n)
        details.append(
            {
                "budget_axis": "absolute",
                "budget_value": budget,
                "budget_count": actual,
                "realized_load": actual / n if n else 0.0,
                **matched_budget_metrics(ordering, event_ids, utilities, actual),
            }
        )
    load_points: dict[float, float] = {0.0: 0.0}
    for fraction in FRACTION_BUDGETS:
        budget = min(n, max(1, int(math.floor(fraction * n))))
        metrics = matched_budget_metrics(ordering, event_ids, utilities, budget)
        realized = budget / n if n else 0.0
        load_points[realized] = float(metrics["capture"])
        details.append(
            {
                "budget_axis": "alarm_load_fraction",
                "budget_value": fraction,
                "budget_count": budget,
                "realized_load": realized,
                **metrics,
            }
        )
    last_capture = load_points[max(load_points)]
    load_points[PRIMARY_MAX_LOAD] = last_capture
    x = np.asarray(sorted(load_points), dtype=float)
    y = np.asarray([load_points[value] for value in x], dtype=float)
    keep = x <= PRIMARY_MAX_LOAD + 1e-12
    auc = float(np.trapezoid(y[keep], x[keep]) / PRIMARY_MAX_LOAD)
    return auc, details


def _ordering_auc_only(
    ordering: np.ndarray, episodes: list[dict], utilities: np.ndarray
) -> float:
    n = len(episodes)
    event_ids = [list(map(int, row["event_ids"])) for row in episodes]
    load_points: dict[float, float] = {0.0: 0.0}
    for fraction in FRACTION_BUDGETS:
        budget = min(n, max(1, int(math.floor(fraction * n))))
        capture = float(
            matched_budget_metrics(ordering, event_ids, utilities, budget)["capture"]
        )
        load_points[budget / n if n else 0.0] = capture
    load_points[PRIMARY_MAX_LOAD] = load_points[max(load_points)]
    x = np.asarray(sorted(load_points), dtype=float)
    y = np.asarray([load_points[value] for value in x], dtype=float)
    keep = x <= PRIMARY_MAX_LOAD + 1e-12
    return float(np.trapezoid(y[keep], x[keep]) / PRIMARY_MAX_LOAD)


def evaluate_policy(
    values: np.ndarray,
    episodes: list[dict],
    utilities: np.ndarray,
    tie_seed: int,
    *,
    include_details: bool = True,
) -> tuple[float, list[dict]]:
    if not include_details:
        aucs = [
            _ordering_auc_only(ordering, episodes, utilities)
            for ordering in tie_orderings(values, tie_seed)
        ]
        return float(np.mean(aucs)), []
    aucs = []
    details_by_draw = []
    for ordering in tie_orderings(values, tie_seed):
        auc, details = _ordering_curve(ordering, episodes, utilities)
        aucs.append(auc)
        details_by_draw.append(details)
    averaged = []
    for row_id in range(len(details_by_draw[0])):
        template = details_by_draw[0][row_id]
        averaged.append(
            {
                key: template[key]
                if key in {"budget_axis", "budget_value", "budget_count", "realized_load"}
                else float(np.mean([draw[row_id][key] for draw in details_by_draw]))
                for key in template
            }
        )
    return float(np.mean(aucs)), averaged


def attainable_upper_bound(
    episodes: list[dict], utilities: np.ndarray
) -> tuple[float, list[dict]]:
    detected = sorted({event_id for row in episodes for event_id in row["event_ids"]})
    detected_utilities = sorted((utilities[event_id] for event_id in detected), reverse=True)
    total = float(utilities.sum())
    n = len(episodes)

    def at_budget(budget: int) -> dict[str, float]:
        budget = min(max(budget, 0), n)
        count = min(budget, len(detected_utilities))
        captured = float(sum(detected_utilities[:count]))
        return {
            "capture": captured / total if total > 0 else 0.0,
            "captured_utility": captured,
            "matched_events": float(count),
            "event_coverage": count / len(utilities) if len(utilities) else 0.0,
            "false_duplicate_review_fraction": 0.0 if budget == 0 else 1.0 - count / budget,
        }

    details = []
    for budget in ABSOLUTE_BUDGETS:
        actual = min(budget, n)
        details.append(
            {
                "budget_axis": "absolute",
                "budget_value": budget,
                "budget_count": actual,
                "realized_load": actual / n if n else 0.0,
                **at_budget(actual),
            }
        )
    points = {0.0: 0.0}
    for fraction in FRACTION_BUDGETS:
        budget = min(n, max(1, int(math.floor(fraction * n))))
        metrics = at_budget(budget)
        realized = budget / n if n else 0.0
        points[realized] = metrics["capture"]
        details.append(
            {
                "budget_axis": "alarm_load_fraction",
                "budget_value": fraction,
                "budget_count": budget,
                "realized_load": realized,
                **metrics,
            }
        )
    points[PRIMARY_MAX_LOAD] = points[max(points)]
    x = np.asarray(sorted(points), dtype=float)
    y = np.asarray([points[value] for value in x], dtype=float)
    keep = x <= PRIMARY_MAX_LOAD + 1e-12
    return float(np.trapezoid(y[keep], x[keep]) / PRIMARY_MAX_LOAD), details


def ndcg_at_k(relevances: list[float], k: int = 10) -> float:
    values = np.asarray(relevances, dtype=float)
    ranked = values[:k]
    dcg = float((ranked / np.log2(np.arange(2, len(ranked) + 2))).sum())
    ideal = np.sort(values)[::-1][:k]
    denominator = float((ideal / np.log2(np.arange(2, len(ideal) + 2))).sum())
    return dcg / denominator if denominator > 0 else 0.0


def dedup_ndcg(
    values: np.ndarray,
    episodes: list[dict],
    utilities: np.ndarray,
    tie_seed: int,
) -> float:
    results = []
    for ordering in tie_orderings(values, tie_seed):
        seen: set[int] = set()
        relevances = []
        for episode_id in ordering:
            candidates = [
                event_id
                for event_id in episodes[int(episode_id)]["event_ids"]
                if event_id not in seen
            ]
            if not candidates:
                relevances.append(0.0)
                continue
            chosen = max(candidates, key=lambda event_id: utilities[event_id])
            seen.add(chosen)
            relevances.append(float(utilities[chosen]))
        results.append(ndcg_at_k(relevances))
    return float(np.mean(results))


def _permuted_context_scores(
    episodes: list[dict], criticality: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    return explanation_policy_scores(
        episodes, rng.permutation(criticality), "occlusion_mass"
    )


def _noise_attribution_scores(
    episodes: list[dict], criticality: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    masses = np.asarray([row["occlusion_mass"] for row in episodes], dtype=float)
    noise = np.vstack([mass[rng.permutation(len(mass))] for mass in masses])
    return score_magnitude(episodes) * (noise @ criticality) / float(np.mean(criticality))


def _within_type_permutation(
    utilities: np.ndarray, events: list[dict], rng: np.random.Generator
) -> np.ndarray:
    result = utilities.copy()
    for fault_type in sorted({event["type"] for event in events}):
        ids = np.asarray(
            [idx for idx, event in enumerate(events) if event["type"] == fault_type]
        )
        result[ids] = rng.permutation(result[ids])
    return result


def confirmatory_decision(
    deltas_by_seed: Iterable[float], *, seed: int = BOOTSTRAP_SEED, b: int = BOOTSTRAP_B
) -> dict:
    """Frozen one-sided 95% lower bound for an iid seed-level mean.

    ``seed`` and ``b`` remain accepted for API compatibility with discovery
    tooling, but the V4 decision is deterministic and uses Student's t rather
    than an anticonservative small-sample percentile bootstrap.
    """

    values = np.asarray(list(deltas_by_seed), dtype=float)
    if len(values) < 2:
        return {
            "method": "one_sample_student_t_lower_bound",
            "n": int(len(values)),
            "mean": float(values.mean()),
            "sd": math.nan,
            "lower_95_one_sided": math.nan,
            "p_one_sided_positive": math.nan,
            "pass": False,
        }
    mean = float(values.mean())
    sd = float(values.std(ddof=1))
    if sd <= 1e-15:
        lower = mean
        p_value = 0.0 if mean > 0 else 1.0
    else:
        se = sd / math.sqrt(len(values))
        lower = float(mean - t.ppf(0.95, len(values) - 1) * se)
        statistic = mean / se
        p_value = float(t.sf(statistic, len(values) - 1))
    return {
        "method": "one_sample_student_t_lower_bound",
        "n": int(len(values)),
        "mean": mean,
        "sd": sd,
        "lower_95_one_sided": lower,
        "p_one_sided_positive": p_value,
        "pass": lower > 0,
    }


def _one_sided_positive_p(values: Iterable[float]) -> float:
    array = np.asarray(list(values), dtype=float)
    if len(array) < 2 or np.allclose(array, array[0]):
        return 1.0
    result = ttest_1samp(array, 0.0)
    p_two = float(result.pvalue)
    return p_two / 2.0 if float(array.mean()) > 0 else 1.0 - p_two / 2.0


def holm_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = np.argsort(np.asarray(p_values), kind="stable")
    adjusted = np.ones(count, dtype=float)
    running = 0.0
    for rank, original_id in enumerate(order):
        candidate = min(1.0, (count - rank) * p_values[int(original_id)])
        running = max(running, candidate)
        adjusted[int(original_id)] = running
    return adjusted.tolist()


def _mean_t_ci(values: Iterable[float]) -> tuple[float, float, float]:
    array = np.asarray(list(values), dtype=float)
    mean = float(array.mean())
    if len(array) < 2:
        return mean, math.nan, math.nan
    radius = float(t.ppf(0.975, len(array) - 1) * array.std(ddof=1) / math.sqrt(len(array)))
    return mean, mean - radius, mean + radius


def _bootstrap_mean_ci(values: list[float], seed: int) -> tuple[float, float, float]:
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    samples = array[rng.integers(0, len(array), size=(BOOTSTRAP_B, len(array)))].mean(axis=1)
    return float(array.mean()), float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))


def power_plan(discovery_deltas: list[float]) -> dict:
    values = np.asarray(discovery_deltas, dtype=float)
    mean = float(values.mean())
    if len(values) < 3 or mean <= 0:
        return {"status": "NO_POSITIVE_EFFECT_FOR_POWER", "recommended_n": None}
    sd = float(values.std(ddof=1))
    sd_upper = float(math.sqrt((len(values) - 1) * sd**2 / chi2.ppf(0.05, len(values) - 1)))
    analytic = int(math.ceil(((norm.ppf(0.95) + norm.ppf(0.80)) * sd_upper / mean) ** 2))
    candidate = max(3, analytic)
    if candidate > POWER_MAX_N:
        return {
            "status": "REQUIRED_N_EXCEEDS_CAP",
            "observed_mean": mean,
            "observed_sd": sd,
            "sd_upper_95": sd_upper,
            "analytic_start_n": candidate,
            "recommended_n": None,
            "cap": POWER_MAX_N,
        }
    master = np.random.default_rng(BOOTSTRAP_SEED + 9000)
    while candidate <= POWER_MAX_N:
        passes = []
        for outer in range(POWER_OUTER):
            simulated = master.normal(mean, sd_upper, size=candidate)
            passes.append(
                confirmatory_decision(
                    simulated,
                    seed=BOOTSTRAP_SEED + 100_000 * candidate + outer,
                )["pass"]
            )
        estimated_power = float(np.mean(passes))
        print(
            f"CRITICALITY_POWER_CANDIDATE n={candidate} "
            f"estimated_power={estimated_power:.4f}",
            flush=True,
        )
        if estimated_power >= 0.80:
            return {
                "status": "POWER_TARGET_REACHED",
                "observed_mean": mean,
                "observed_sd": sd,
                "sd_upper_95": sd_upper,
                "analytic_start_n": analytic,
                "recommended_n": candidate,
                "simulated_power": estimated_power,
                "outer_simulations": POWER_OUTER,
                "bootstrap_b": BOOTSTRAP_B,
            }
        candidate = max(candidate + 1, int(math.ceil(candidate * 1.10)))
    return {"status": "REQUIRED_N_EXCEEDS_CAP", "recommended_n": None, "cap": POWER_MAX_N}


def _normalise_mass(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mass = np.maximum(np.asarray(values, dtype=float), 0.0)
    totals = mass.sum(axis=-1, keepdims=True)
    degenerate = np.squeeze(totals <= 1e-12, axis=-1)
    safe = np.divide(mass, totals, out=np.zeros_like(mass), where=totals > 1e-12)
    safe = np.where(np.expand_dims(degenerate, -1), 1.0 / 12, safe)
    return safe, np.asarray(degenerate, dtype=bool)


def _recompute_aggregated_mass(
    raw: np.ndarray, episodes: list[dict], weights: np.ndarray
) -> np.ndarray:
    result = np.empty((raw.shape[0], len(episodes), 12), dtype=float)
    cursor = 0
    for episode_id, episode in enumerate(episodes):
        count = int(episode["window_end"] - episode["window_start"] + 1)
        window_mass, _ = _normalise_mass(raw[:, cursor : cursor + count])
        local_weights = weights[cursor : cursor + count]
        local_weights = local_weights / max(float(local_weights.sum()), 1e-12)
        result[:, episode_id], _ = _normalise_mass(
            (window_mass * local_weights[None, :, None]).sum(axis=1)
        )
        cursor += count
    if cursor != raw.shape[1]:
        raise RuntimeError("raw episode aggregation cursor mismatch")
    mean_mass, _ = _normalise_mass(result.mean(axis=0))
    return mean_mass


def property_tests(
    run_root: Path,
    seeds: list[int],
    models: list[str],
    model_seeds: list[int] | None = None,
    expected_amplitude_scale: float = 1.0,
) -> dict:
    checks: list[dict] = []
    pooled_events: list[dict] = []
    event_seed: list[int] = []
    amplitude_scales: dict[str, float] = {}
    raw_checks_pass = True
    for seed in seeds:
        data_path = run_root / "data" / f"telemetry_seed{seed}.npz"
        with np.load(data_path) as dataset:
            observed_amplitude = float(dataset["amplitude_scale"])
            amplitude_scales[str(seed)] = observed_amplitude
            checks.append(
                {
                    "id": f"amplitude_scale_seed{seed}",
                    "pass": bool(
                        np.isclose(
                            observed_amplitude,
                            expected_amplitude_scale,
                            rtol=0.0,
                            atol=1e-12,
                        )
                    ),
                    "value": observed_amplitude,
                    "expected": expected_amplitude_scale,
                }
            )
            events = json.loads(str(dataset["ev_te"]))
            difference = np.abs(dataset["Xte"] - dataset["Xte_nominal"]) / np.maximum(
                dataset["train_sigma"][None, :], 1e-9
            )
            for event in events:
                recomputed = difference[event["start"] : event["end"]].mean(axis=0)
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
            pooled_events.extend(events)
            event_seed.extend([seed] * len(events))
    checks.append({"id": "raw_counterfactual_channel_impact", "pass": raw_checks_pass})

    impacts = np.asarray([event["impact"] for event in pooled_events], dtype=float)
    types = np.asarray([event["type"] for event in pooled_events])
    seeds_array = np.asarray(event_seed)
    type_auc = {}
    for fault_type in sorted(set(types)):
        auc = float(roc_auc_score(types == fault_type, impacts))
        directionless = max(auc, 1.0 - auc)
        type_auc[fault_type] = directionless
        checks.append(
            {
                "id": f"type_impact_auc_{fault_type}",
                "pass": directionless <= TYPE_ONE_VS_REST_AUC_MAX,
                "value": directionless,
                "maximum": TYPE_ONE_VS_REST_AUC_MAX,
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
    multiclass_auc = float(roc_auc_score(binary, probabilities, average="macro", multi_class="ovr"))
    checks.append(
        {
            "id": "leave_one_seed_out_type_from_impact_auc",
            "pass": multiclass_auc <= TYPE_MULTICLASS_AUC_MAX,
            "value": multiclass_auc,
            "maximum": TYPE_MULTICLASS_AUC_MAX,
        }
    )
    utility_shares = {}
    for scenario, vector in SCENARIOS.items():
        utilities = event_utilities(pooled_events, vector)
        utility_shares[scenario] = {}
        for fault_type in classes:
            share = float(utilities[types == fault_type].sum() / utilities.sum())
            utility_shares[scenario][fault_type] = share
            checks.append(
                {
                    "id": f"type_utility_share_{scenario}_{fault_type}",
                    "pass": share <= TYPE_UTILITY_SHARE_MAX,
                    "value": share,
                    "maximum": TYPE_UTILITY_SHARE_MAX,
                }
            )

    reordered = []
    if models:
        for seed in (seeds if model_seeds is None else model_seeds):
            events = load_events(run_root, seed)
            for model in models:
                payload = load_payload(run_root, seed, model)
                episodes = payload["episodes"]
                checks.append(
                    {
                        "id": f"minimum_episode_count_seed{seed}_{model}",
                        "pass": len(episodes) >= MIN_EPISODES,
                        "value": len(episodes),
                        "minimum": MIN_EPISODES,
                    }
                )
                checks.append(
                    {
                        "id": f"tie_pair_mass_seed{seed}_{model}",
                        "pass": (
                            tied_pair_mass(score_magnitude(episodes)) <= TIE_PAIR_MASS_MAX
                            if model in PRIMARY_CONFIRMATORY_MODELS
                            else True
                        ),
                        "value": tied_pair_mass(score_magnitude(episodes)),
                        "maximum": TIE_PAIR_MASS_MAX,
                        "enforced_for_confirmatory_primary": model
                        in PRIMARY_CONFIRMATORY_MODELS,
                        "cell_claim_gate_open": tied_pair_mass(score_magnitude(episodes))
                        <= TIE_PAIR_MASS_MAX,
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
                        {"id": f"mass_complete_seed{seed}_{model}_{mass_key}", "pass": bool(valid)}
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
                        "pass": degenerate_rate <= DEGENERATE_RATE_MAX,
                        "value": degenerate_rate,
                        "maximum": DEGENERATE_RATE_MAX,
                    }
                )
                npz_path = run_root / "ckpt" / f"model_seed{seed}_{model}.npz"
                with np.load(npz_path) as artifact:
                    peak = artifact["episode_peak"]
                    mean_test = artifact["mean_test"]
                    mean_val = artifact["mean_val"]
                    original = tail_surprisal(mean_test[peak], mean_val)
                    transforms = (
                        (mean_test * 3.7 + 2.0, mean_val * 3.7 + 2.0),
                        (mean_test**3, mean_val**3),
                        (np.log1p(mean_test), np.log1p(mean_val)),
                    )
                    invariant = all(
                        np.allclose(original, tail_surprisal(test_values[peak], val_values))
                        for test_values, val_values in transforms
                    )
                    checks.append(
                        {"id": f"monotone_score_invariance_seed{seed}_{model}", "pass": bool(invariant)}
                    )
                    native_recomputed = _recompute_aggregated_mass(
                        artifact["raw_window_native"], episodes, artifact["window_tail_weights"]
                    )
                    occlusion_recomputed = _recompute_aggregated_mass(
                        artifact["raw_window_occlusion"], episodes, artifact["window_tail_weights"]
                    )
                    aggregation_valid = np.allclose(
                        native_recomputed, artifact["episode_native_mass"], atol=1e-10
                    ) and np.allclose(
                        occlusion_recomputed, artifact["episode_occlusion_mass"], atol=1e-10
                    )
                    checks.append(
                        {"id": f"episode_aggregation_seed{seed}_{model}", "pass": bool(aggregation_valid)}
                    )
                uniform = policy_scores(episodes, events, SCENARIOS["uniform"])
                checks.append(
                    {
                        "id": f"uniform_identity_seed{seed}_{model}",
                        "pass": bool(
                            np.allclose(uniform["score_only"], uniform["native_explanation_context"])
                            and np.allclose(uniform["score_only"], uniform["occlusion_context"])
                        ),
                    }
                )
                for scenario in NONUNIFORM_SCENARIOS:
                    values = policy_scores(episodes, events, SCENARIOS[scenario])
                    tau_value = float(
                        kendalltau(values["score_only"], values["occlusion_context"]).statistic
                    )
                    reordered.append(tau_value < 0.999999)
                    utilities = event_utilities(events, SCENARIOS[scenario])
                    upper, _ = attainable_upper_bound(episodes, utilities)
                    maximum_policy = max(
                        evaluate_policy(
                            values[policy],
                            episodes,
                            utilities,
                            BOOTSTRAP_SEED + seed * 100 + M.MODELS.index(model),
                        )[0]
                        for policy in POLICIES
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
                "pass": reordered_fraction >= REORDERED_CELL_FRACTION_MIN,
                "value": reordered_fraction,
                "minimum": REORDERED_CELL_FRACTION_MIN,
            }
        )

    duplicate = matched_budget_metrics(
        np.asarray([0, 1, 2]), [[0], [0], [1]], np.asarray([10.0, 5.0]), 2
    )
    merged = matched_budget_metrics(np.asarray([0]), [[0, 1]], np.asarray([10.0, 5.0]), 1)
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
        "generator_seeds": list(seeds),
        "model_seeds": list(seeds if model_seeds is None else model_seeds),
        "models": list(models),
        "primary_confirmatory_models": list(PRIMARY_CONFIRMATORY_MODELS),
        "expected_amplitude_scale": expected_amplitude_scale,
        "amplitude_scales": amplitude_scales,
        "type_impact_auc": type_auc,
        "multiclass_type_from_impact_auc": multiclass_auc,
        "type_utility_shares": utility_shares,
        "checks": checks,
    }


def analyze(run_root: Path, seeds: list[int], null_draws: int) -> dict:
    metrics_dir = run_root / "metrics"
    summary_rows: list[dict] = []
    budget_rows: list[dict] = []
    null_rows: list[dict] = []
    utility_null_rows: list[dict] = []
    information_null_rows: list[dict] = []
    dedup_rows: list[dict] = []
    analysis_code_sha256 = file_sha256(Path(__file__).resolve())
    run_manifest = json.loads(
        (run_root / "RUN_MANIFEST.json").read_text(encoding="utf-8")
    )
    run_contract_sha256 = run_manifest.get("run_contract_sha256")
    if not isinstance(run_contract_sha256, str) or len(run_contract_sha256) != 64:
        raise RuntimeError("RUN_MANIFEST.json lacks a frozen run_contract_sha256")

    for seed in seeds:
        checkpoint_path = run_root / "analysis_ckpt" / f"seed{seed}.json"
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            expected_contract = {
                "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
                "analysis_code_sha256": analysis_code_sha256,
                "run_contract_sha256": run_contract_sha256,
                "null_draws": null_draws,
                "seed": seed,
            }
            observed_contract = {
                key: checkpoint.get(key) for key in expected_contract
            }
            if observed_contract != expected_contract:
                raise RuntimeError(
                    "analysis checkpoint contract mismatch: "
                    f"{checkpoint_path} expected={expected_contract} "
                    f"observed={observed_contract}"
                )
            summary_rows.extend(checkpoint["summary_rows"])
            budget_rows.extend(checkpoint["budget_rows"])
            null_rows.extend(checkpoint["null_rows"])
            utility_null_rows.extend(checkpoint["utility_null_rows"])
            information_null_rows.extend(checkpoint["information_null_rows"])
            dedup_rows.extend(checkpoint["dedup_rows"])
            print(
                f"CRITICALITY_ANALYSIS_SEED_RESUMED seed={seed} "
                f"null_draws={null_draws}",
                flush=True,
            )
            continue
        starts = {
            "summary": len(summary_rows),
            "budget": len(budget_rows),
            "null": len(null_rows),
            "utility_null": len(utility_null_rows),
            "information_null": len(information_null_rows),
            "dedup": len(dedup_rows),
        }
        events = load_events(run_root, seed)
        for model in M.MODELS:
            payload = load_payload(run_root, seed, model)
            episodes = payload["episodes"]
            if len(episodes) < MIN_EPISODES:
                raise RuntimeError(f"minimum episode gate failed seed={seed} model={model}")
            for scenario_id, (scenario, criticality) in enumerate(SCENARIOS.items()):
                utilities = event_utilities(events, criticality)
                scores = policy_scores(episodes, events, criticality)
                tie_seed = BOOTSTRAP_SEED + 100_000 * seed + 1_000 * M.MODELS.index(model) + scenario_id
                auc_by_policy = {}
                for policy in POLICIES:
                    auc, details = evaluate_policy(scores[policy], episodes, utilities, tie_seed)
                    auc_by_policy[policy] = auc
                    summary_rows.append(
                        {
                            "seed": seed,
                            "model": model,
                            "family": M.FAMILY[model],
                            "scenario": scenario,
                            "policy": policy,
                            "muc_auc_0_40": auc,
                            "n_episodes": len(episodes),
                            "tied_pair_mass": tied_pair_mass(scores[policy]),
                        }
                    )
                    for detail in details:
                        budget_rows.append(
                            {"seed": seed, "model": model, "scenario": scenario, "policy": policy, **detail}
                        )
                upper, upper_details = attainable_upper_bound(episodes, utilities)
                summary_rows.append(
                    {
                        "seed": seed,
                        "model": model,
                        "family": M.FAMILY[model],
                        "scenario": scenario,
                        "policy": "attainable_utility_upper_bound",
                        "muc_auc_0_40": upper,
                        "n_episodes": len(episodes),
                        "tied_pair_mass": 0.0,
                    }
                )
                for detail in upper_details:
                    budget_rows.append(
                        {
                            "seed": seed,
                            "model": model,
                            "scenario": scenario,
                            "policy": "attainable_utility_upper_bound",
                            **detail,
                        }
                    )
                dedup_rows.append(
                    {
                        "seed": seed,
                        "model": model,
                        "scenario": scenario,
                        "score_only_dedup_ndcg10": dedup_ndcg(
                            scores["score_only"], episodes, utilities, tie_seed
                        ),
                        "score_only_muc_auc_0_40": auc_by_policy["score_only"],
                    }
                )
                if scenario == "uniform":
                    continue
                for draw in range(null_draws):
                    for control_id, scorer in (
                        ("permuted_context", _permuted_context_scores),
                        ("noise_attribution_context", _noise_attribution_scores),
                    ):
                        rng = np.random.default_rng(
                            10_000_019 * seed
                            + 100_003 * M.MODELS.index(model)
                            + 1_009 * scenario_id
                            + 17 * draw
                            + (1 if control_id == "permuted_context" else 2)
                        )
                        null_auc, _ = evaluate_policy(
                            scorer(episodes, criticality, rng),
                            episodes,
                            utilities,
                            tie_seed,
                            include_details=False,
                        )
                        null_rows.append(
                            {
                                "seed": seed,
                                "model": model,
                                "scenario": scenario,
                                "control": control_id,
                                "draw": draw,
                                "gain": null_auc - auc_by_policy["score_only"],
                            }
                        )
                    rng = np.random.default_rng(
                        70_000_027 * seed
                        + 700_001 * M.MODELS.index(model)
                        + 7_001 * scenario_id
                        + draw
                    )
                    permuted_utility = _within_type_permutation(utilities, events, rng)
                    baseline_null, _ = evaluate_policy(
                        scores["score_only"],
                        episodes,
                        permuted_utility,
                        tie_seed,
                        include_details=False,
                    )
                    occlusion_null, _ = evaluate_policy(
                        scores["occlusion_context"],
                        episodes,
                        permuted_utility,
                        tie_seed,
                        include_details=False,
                    )
                    utility_null_rows.append(
                        {
                            "seed": seed,
                            "model": model,
                            "scenario": scenario,
                            "draw": draw,
                            "gain": occlusion_null - baseline_null,
                        }
                    )
                    for control_id, scorer in (
                        ("permuted_context", _permuted_context_scores),
                        ("noise_attribution_context", _noise_attribution_scores),
                    ):
                        control_rng = np.random.default_rng(
                            10_000_019 * seed
                            + 100_003 * M.MODELS.index(model)
                            + 1_009 * scenario_id
                            + 17 * draw
                            + (1 if control_id == "permuted_context" else 2)
                        )
                        control_scores = scorer(episodes, criticality, control_rng)
                        control_true_auc, _ = evaluate_policy(
                            control_scores,
                            episodes,
                            utilities,
                            tie_seed,
                            include_details=False,
                        )
                        control_permuted_auc, _ = evaluate_policy(
                            control_scores,
                            episodes,
                            permuted_utility,
                            tie_seed,
                            include_details=False,
                        )
                        information_null_rows.append(
                            {
                                "seed": seed,
                                "model": model,
                                "scenario": scenario,
                                "control": control_id,
                                "draw": draw,
                                "information_contrast": (
                                    control_true_auc
                                    - auc_by_policy["score_only"]
                                    - (control_permuted_auc - baseline_null)
                                ),
                            }
                        )
        write_json(
            checkpoint_path,
            {
                "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
                "analysis_code_sha256": analysis_code_sha256,
                "run_contract_sha256": run_contract_sha256,
                "seed": seed,
                "null_draws": null_draws,
                "summary_rows": summary_rows[starts["summary"] :],
                "budget_rows": budget_rows[starts["budget"] :],
                "null_rows": null_rows[starts["null"] :],
                "utility_null_rows": utility_null_rows[starts["utility_null"] :],
                "information_null_rows": information_null_rows[
                    starts["information_null"] :
                ],
                "dedup_rows": dedup_rows[starts["dedup"] :],
            },
        )
        print(
            f"CRITICALITY_ANALYSIS_SEED_OK seed={seed} null_draws={null_draws}",
            flush=True,
        )

    write_csv(metrics_dir / "policy_summary.csv", summary_rows)
    write_csv(metrics_dir / "budget_curve.csv", budget_rows)
    write_csv(metrics_dir / "null_draws.csv", null_rows)
    write_csv(metrics_dir / "utility_permutation_null.csv", utility_null_rows)
    write_csv(metrics_dir / "information_contrast_null.csv", information_null_rows)
    write_csv(metrics_dir / "repaired_dedup_redundancy_seed.csv", dedup_rows)

    index = {
        (int(row["seed"]), row["model"], row["scenario"], row["policy"]): float(row["muc_auc_0_40"])
        for row in summary_rows
    }
    family_cells = [(model, scenario) for model in M.MODELS for scenario in NONUNIFORM_SCENARIOS]
    tie_eligible_models = [
        model
        for model in M.MODELS
        if max(
            row["tied_pair_mass"]
            for row in summary_rows
            if row["model"] == model and row["policy"] == "score_only"
        )
        <= TIE_PAIR_MASS_MAX
    ]
    tie_eligible_cells = [
        (model, scenario)
        for model, scenario in family_cells
        if model in tie_eligible_models
    ]
    cell_rows = []
    p_values = []
    for model, scenario in family_cells:
        deltas = [
            index[(seed, model, scenario, "occlusion_context")]
            - index[(seed, model, scenario, "score_only")]
            for seed in seeds
        ]
        native = [
            index[(seed, model, scenario, "native_explanation_context")]
            - index[(seed, model, scenario, "score_only")]
            for seed in seeds
        ]
        mean, low, high = _mean_t_ci(deltas)
        native_mean, native_low, native_high = _mean_t_ci(native)
        p_values.append(_one_sided_positive_p(deltas))
        cell_rows.append(
            {
                "model": model,
                "scenario": scenario,
                "gain_mean": mean,
                "t_ci_low": low,
                "t_ci_high": high,
                "native_gain_mean": native_mean,
                "native_t_ci_low": native_low,
                "native_t_ci_high": native_high,
                "one_sided_p": p_values[-1],
                "holm_p": math.nan,
                "cell_claim_eligible": model in tie_eligible_models,
                "n_seeds": len(seeds),
            }
        )
    for row, adjusted in zip(cell_rows, holm_adjust(p_values)):
        row["holm_p"] = adjusted
    write_csv(metrics_dir / "cell_decisions.csv", cell_rows)

    omnibus = []
    native_omnibus = []
    for seed in seeds:
        omnibus.append(
            float(
                np.mean(
                    [
                        index[(seed, model, scenario, "occlusion_context")]
                        - index[(seed, model, scenario, "score_only")]
                        for model, scenario in family_cells
                    ]
                )
            )
        )
        native_omnibus.append(
            float(
                np.mean(
                    [
                        index[(seed, model, scenario, "native_explanation_context")]
                        - index[(seed, model, scenario, "score_only")]
                        for model, scenario in family_cells
                    ]
                )
            )
        )
    primary_decision = confirmatory_decision(omnibus)
    native_decision = confirmatory_decision(native_omnibus, seed=BOOTSTRAP_SEED + 1)
    tie_eligible_omnibus = []
    for seed in seeds:
        tie_eligible_omnibus.append(
            float(
                np.mean(
                    [
                        index[(seed, model, scenario, "occlusion_context")]
                        - index[(seed, model, scenario, "score_only")]
                        for model, scenario in tie_eligible_cells
                    ]
                )
            )
        )
    tie_eligible_decision = confirmatory_decision(
        tie_eligible_omnibus, seed=BOOTSTRAP_SEED + 2
    )

    null_family_rates: dict[str, dict[str, float]] = {}
    for control in ("permuted_context", "noise_attribution_context"):
        null_family_rates[control] = {}
        for scenario in NONUNIFORM_SCENARIOS:
            declarations = []
            for draw in range(null_draws):
                per_seed = []
                for seed in seeds:
                    gains = [
                        row["gain"]
                        for row in null_rows
                        if row["control"] == control
                        and row["scenario"] == scenario
                        and row["draw"] == draw
                        and row["seed"] == seed
                        and row["model"] in PRIMARY_CONFIRMATORY_MODELS
                    ]
                    if len(gains) != len(PRIMARY_CONFIRMATORY_MODELS):
                        raise RuntimeError(
                            f"incomplete null cells seed={seed} scenario={scenario} "
                            f"control={control} draw={draw}"
                        )
                    per_seed.append(float(np.mean(gains)))
                declarations.append(confirmatory_decision(per_seed)["pass"])
            null_family_rates[control][scenario] = float(np.mean(declarations))

    utility_null_by_scenario: dict[str, dict[str, float]] = {}
    utility_null_false_gain_rates: dict[str, float] = {}
    for scenario in NONUNIFORM_SCENARIOS:
        draw_means = []
        declarations = []
        for draw in range(null_draws):
            per_seed = []
            for seed in seeds:
                gains = [
                    row["gain"]
                    for row in utility_null_rows
                    if row["scenario"] == scenario
                    and row["draw"] == draw
                    and row["seed"] == seed
                    and row["model"] in PRIMARY_CONFIRMATORY_MODELS
                ]
                if len(gains) != len(PRIMARY_CONFIRMATORY_MODELS):
                    raise RuntimeError(
                        f"incomplete utility-null cells seed={seed} "
                        f"scenario={scenario} draw={draw}"
                    )
                per_seed.append(float(np.mean(gains)))
            draw_means.append(float(np.mean(per_seed)))
            declarations.append(confirmatory_decision(per_seed)["pass"])
        utility_null_by_scenario[scenario] = {
            "mean_gain": float(np.mean(draw_means)),
            "minimum_draw_mean": float(np.min(draw_means)),
            "maximum_draw_mean": float(np.max(draw_means)),
        }
        utility_null_false_gain_rates[scenario] = float(np.mean(declarations))

    information_null_false_gain_rates: dict[str, dict[str, float]] = {}
    for control in ("permuted_context", "noise_attribution_context"):
        information_null_false_gain_rates[control] = {}
        for scenario in NONUNIFORM_SCENARIOS:
            declarations = []
            for draw in range(null_draws):
                per_seed = []
                for seed in seeds:
                    contrasts = [
                        row["information_contrast"]
                        for row in information_null_rows
                        if row["control"] == control
                        and row["scenario"] == scenario
                        and row["draw"] == draw
                        and row["seed"] == seed
                        and row["model"] in PRIMARY_CONFIRMATORY_MODELS
                    ]
                    if len(contrasts) != len(PRIMARY_CONFIRMATORY_MODELS):
                        raise RuntimeError(
                            f"incomplete information-null cells seed={seed} "
                            f"scenario={scenario} control={control} draw={draw}"
                        )
                    per_seed.append(float(np.mean(contrasts)))
                declarations.append(confirmatory_decision(per_seed)["pass"])
            information_null_false_gain_rates[control][scenario] = float(
                np.mean(declarations)
            )

    tau_rows = []
    old_tau_values = []
    scenario_tau_values = []
    for seed in seeds:
        scenario_muc = {}
        for scenario in SCENARIOS:
            muc = [index[(seed, model, scenario, "score_only")] for model in M.MODELS]
            dedup = [
                row["score_only_dedup_ndcg10"]
                for model in M.MODELS
                for row in dedup_rows
                if row["seed"] == seed and row["model"] == model and row["scenario"] == scenario
            ]
            tau_value = float(kendalltau(dedup, muc).statistic)
            old_tau_values.append(tau_value)
            scenario_muc[scenario] = muc
            tau_rows.append({"seed": seed, "comparison": f"repaired_dedup_vs_muc_{scenario}", "kendall_tau": tau_value})
        scenario_tau = float(
            kendalltau(scenario_muc["platform_survival"], scenario_muc["payload_first"]).statistic
        )
        scenario_tau_values.append(scenario_tau)
        tau_rows.append({"seed": seed, "comparison": "platform_vs_payload_muc", "kendall_tau": scenario_tau})
    write_csv(metrics_dir / "repaired_redundancy_kendall_seed.csv", tau_rows)
    redundancy_mean, redundancy_low, redundancy_high = _bootstrap_mean_ci(
        old_tau_values, BOOTSTRAP_SEED + 500
    )
    scenario_mean, scenario_low, scenario_high = _bootstrap_mean_ci(
        scenario_tau_values, BOOTSTRAP_SEED + 501
    )

    conflicts = [
        row
        for row in cell_rows
        if np.sign(row["gain_mean"]) != np.sign(row["native_gain_mean"])
        and not (row["t_ci_low"] <= 0 <= row["t_ci_high"])
        and not (row["native_t_ci_low"] <= 0 <= row["native_t_ci_high"])
    ]
    decision = {
        "status": "DISCOVERY_COMPLETE",
        "not_confirmatory_evidence": True,
        "primary_omnibus": primary_decision,
        "tie_eligible_sensitivity_omnibus": tie_eligible_decision,
        "tie_eligible_models": tie_eligible_models,
        "native_omnibus": native_decision,
        "power_plan": power_plan(omnibus),
        "tie_eligible_power_plan": power_plan(tie_eligible_omnibus),
        "null_false_gain_rates_by_control_and_scenario": null_family_rates,
        "within_type_utility_null_by_scenario": utility_null_by_scenario,
        "within_type_utility_null_false_gain_rates": utility_null_false_gain_rates,
        "information_contrast_null_false_gain_rates": information_null_false_gain_rates,
        "repaired_redundancy": {
            "dedup_vs_muc_tau_mean": redundancy_mean,
            "dedup_vs_muc_tau_ci_low": redundancy_low,
            "dedup_vs_muc_tau_ci_high": redundancy_high,
            "platform_vs_payload_tau_mean": scenario_mean,
            "platform_vs_payload_tau_ci_low": scenario_low,
            "platform_vs_payload_tau_ci_high": scenario_high,
        },
        "kill_switches": {
            "null_false_gain_rate_gt_0_05": max(
                rate
                for by_scenario in null_family_rates.values()
                for rate in by_scenario.values()
            )
            > 0.05,
            "within_type_utility_null_false_gain_rate_gt_0_05": max(
                utility_null_false_gain_rates.values()
            )
            > 0.05,
            "information_contrast_null_false_gain_rate_gt_0_05": max(
                rate
                for by_scenario in information_null_false_gain_rates.values()
                for rate in by_scenario.values()
            )
            > 0.05,
            "metric_redundancy_without_scenario_disagreement": bool(
                redundancy_low >= 0.90 and scenario_low >= 0.90
            ),
            "systematic_native_occlusion_conflict": len(conflicts) > len(family_cells) / 2,
            "no_positive_primary_omnibus_for_power": primary_decision["mean"] <= 0,
            "no_positive_tie_eligible_sensitivity_for_power": tie_eligible_decision[
                "mean"
            ]
            <= 0,
        },
        "native_occlusion_conflict_cells": [f"{row['model']}|{row['scenario']}" for row in conflicts],
        "scenario_vectors": {
            name: {channel: float(vector[idx]) for idx, channel in enumerate(CH_NAMES)}
            for name, vector in SCENARIOS.items()
        },
        "frozen_constants": {
            "tie_draws": TIE_DRAWS,
            "confirmatory_method": "one_sample_student_t_lower_bound",
            "confirmatory_one_sided_alpha": 0.05,
            "minimum_episodes": MIN_EPISODES,
        },
    }
    write_json(metrics_dir / "construct_validity.json", decision)
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    property_parser = commands.add_parser("property")
    property_parser.add_argument("--run-root", type=Path, required=True)
    property_parser.add_argument("--seeds", default="0-9")
    property_parser.add_argument("--models", default="")
    property_parser.add_argument(
        "--model-seeds",
        default=None,
        help="Optional model-artifact seed range; generator gates still use --seeds.",
    )
    property_parser.add_argument("--expected-amplitude-scale", type=float, default=1.0)
    analysis_parser = commands.add_parser("analyze")
    analysis_parser.add_argument("--run-root", type=Path, required=True)
    analysis_parser.add_argument("--seeds", default="0-9")
    analysis_parser.add_argument("--null-draws", type=int, default=200)
    args = parser.parse_args()
    seeds = parse_seed_spec(args.seeds)
    if args.command == "property":
        models = [value.strip() for value in args.models.split(",") if value.strip()]
        model_seeds = parse_seed_spec(args.model_seeds) if args.model_seeds else None
        result = property_tests(
            args.run_root,
            seeds,
            models,
            model_seeds,
            args.expected_amplitude_scale,
        )
        write_json(args.run_root / "metrics" / "property_tests.json", result)
        print(f"CRITICALITY_V4_PROPERTY_{result['status']} checks={result['n_checks']} failed={len(result['failed'])}")
        if result["failed"]:
            raise SystemExit(1)
    else:
        decision = analyze(args.run_root, seeds, args.null_draws)
        print(json.dumps(_json_safe(decision), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()

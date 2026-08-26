"""Resumable units for the criticality-conditioned discovery experiment.

Units are ``gen:<seed>``, ``feat:<seed>``, ``model:<seed>:<name>``, and
``cross:<seed>``.  Every artifact is written below the explicitly supplied run
root, so the historical data, checkpoints, and results remain untouched.

Operation: f07-criticality-conditioned-uplift-20260826
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    NCH,
    event_metrics,
    spearman,
    topk_jaccard,
    window_features,
    window_labels,
    windows_of_event,
)
from criticality_generator import generate_seed_v2  # noqa: E402
import models as M  # noqa: E402


N_REP = 3
TOPK = 3


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.npz")
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, path)


def _paths(run_root: Path) -> tuple[Path, Path, Path]:
    data = run_root / "data"
    ckpt = run_root / "ckpt"
    raw = run_root / "raw"
    for path in (data, ckpt, raw):
        path.mkdir(parents=True, exist_ok=True)
    return data, ckpt, raw


def _normalise_mass(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Normalise nonnegative channel mass; a degenerate row becomes uniform."""

    mass = np.maximum(np.asarray(values, dtype=float), 0.0)
    totals = mass.sum(axis=-1, keepdims=True)
    degenerate = np.squeeze(totals <= 1e-12, axis=-1)
    safe = np.divide(mass, totals, out=np.zeros_like(mass), where=totals > 1e-12)
    safe = np.where(np.expand_dims(degenerate, -1), 1.0 / NCH, safe)
    return safe, np.asarray(degenerate, dtype=bool)


def _tail_surprisal(query: np.ndarray, nominal_validation: np.ndarray) -> np.ndarray:
    """Validation ECDF tail magnitude with monotone-invariant queue refinement.

    Query scores falling in the same validation-ECDF bin are ordered within the
    current review queue. Exact raw-score ties remain ties and are handled later
    by the frozen random tie procedure.
    """

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


def _episode_event_ids(
    episode: tuple[int, int], starts: np.ndarray, events: list[dict]
) -> list[int]:
    a, b = episode
    overlapping: list[int] = []
    for event_id, event in enumerate(events):
        event_windows = windows_of_event(starts, event)
        if len(event_windows) and np.any((event_windows >= a) & (event_windows <= b)):
            overlapping.append(event_id)
    return overlapping


def unit_generate(run_root: Path, seed: int, amplitude_scale: float = 1.0) -> None:
    data, _, _ = _paths(run_root)
    output = data / f"telemetry_seed{seed}.npz"
    if output.exists():
        with np.load(output) as dataset:
            observed_scale = float(dataset["amplitude_scale"])
        if not np.isclose(observed_scale, amplitude_scale, rtol=0.0, atol=1e-12):
            raise RuntimeError(
                f"existing seed amplitude mismatch seed={seed} "
                f"expected={amplitude_scale} observed={observed_scale}"
            )
        return
    temporary = output.with_suffix(".tmp.npz")
    generate_seed_v2(seed, temporary, amplitude_scale=amplitude_scale)
    os.replace(temporary, output)


def unit_features(run_root: Path, seed: int) -> None:
    data, ckpt, _ = _paths(run_root)
    output = ckpt / f"feat_seed{seed}.npz"
    if output.exists():
        return
    source = data / f"telemetry_seed{seed}.npz"
    if not source.exists():
        raise FileNotFoundError(f"generator checkpoint missing: {source}")
    with np.load(source) as dataset:
        result: dict[str, np.ndarray] = {}
        for part in ("Xtr", "Xval", "Xtl", "Xte"):
            features, starts = window_features(dataset[part])
            result[part + "_F"] = features
            result[part + "_S"] = starts
        train_mean = result["Xtr_F"].mean(axis=0)
        train_sd = result["Xtr_F"].std(axis=0) + 1e-9
        for part in ("Xtr", "Xval", "Xtl", "Xte"):
            result[part + "_F"] = (result[part + "_F"] - train_mean) / train_sd
        result["ytl_w"] = window_labels(result["Xtl_S"], dataset["ytl"])
        result["yte_w"] = window_labels(result["Xte_S"], dataset["yte"])
        result["feature_train_mean"] = train_mean
        result["feature_train_sd"] = train_sd
    _atomic_npz(output, **result)


def _load(run_root: Path, seed: int) -> tuple[dict[str, np.ndarray], list[dict]]:
    data, ckpt, _ = _paths(run_root)
    feature_path = ckpt / f"feat_seed{seed}.npz"
    data_path = data / f"telemetry_seed{seed}.npz"
    if not feature_path.exists() or not data_path.exists():
        raise FileNotFoundError(f"missing feature/data checkpoint for seed {seed}")
    with np.load(feature_path) as loaded:
        features = {key: loaded[key] for key in loaded.files}
    with np.load(data_path) as dataset:
        events = json.loads(str(dataset["ev_te"]))
    return features, events


def _attribute_replicates(
    name: str,
    models: list,
    queries: np.ndarray,
    background: np.ndarray,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    native = []
    occlusion = []
    for replicate, model in enumerate(models):
        native.append(M.native_attr(name, model, queries, background))
        rng = np.random.default_rng(1_000_003 * seed + 10_007 * replicate + 29)
        occlusion.append(M.occlusion_attr(name, model, queries, background, rng))
    return np.asarray(native), np.asarray(occlusion)


def _mean_mass(replicate_attributions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    replicate_mass, replicate_degenerate = _normalise_mass(replicate_attributions)
    mean_mass = replicate_mass.mean(axis=0)
    mean_mass, mean_degenerate = _normalise_mass(mean_mass)
    all_degenerate = np.all(replicate_degenerate, axis=0) | mean_degenerate
    return mean_mass, all_degenerate


def _aggregate_episode_attributions(
    raw_attributions: np.ndarray,
    episodes: list[tuple[int, int]],
    score_weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Score-weighted mean of per-window normalized mass over each episode."""

    aggregated = np.empty((N_REP, len(episodes), NCH), dtype=float)
    episode_degenerate = np.zeros(len(episodes), dtype=bool)
    cursor = 0
    for episode_id, (first, last) in enumerate(episodes):
        count = last - first + 1
        stop = cursor + count
        window_mass, window_degenerate = _normalise_mass(
            raw_attributions[:, cursor:stop]
        )
        weights = np.asarray(score_weights[cursor:stop], dtype=float)
        weights = weights / max(float(weights.sum()), 1e-12)
        replicate_mass = (window_mass * weights[None, :, None]).sum(axis=1)
        replicate_mass, replicate_degenerate = _normalise_mass(replicate_mass)
        aggregated[:, episode_id] = replicate_mass
        episode_degenerate[episode_id] = bool(
            np.all(window_degenerate) or np.all(replicate_degenerate)
        )
        cursor = stop
    if cursor != raw_attributions.shape[1]:
        raise RuntimeError("episode attribution cursor mismatch")
    mean_mass, mean_degenerate = _mean_mass(aggregated)
    return aggregated, mean_mass, episode_degenerate | mean_degenerate


def _stability(replicate_attributions: np.ndarray, item: int) -> tuple[float, float]:
    jaccard = []
    rho = []
    for first in range(N_REP):
        for second in range(first + 1, N_REP):
            jaccard.append(
                topk_jaccard(
                    replicate_attributions[first, item],
                    replicate_attributions[second, item],
                    TOPK,
                )
            )
            rho.append(
                spearman(
                    replicate_attributions[first, item],
                    replicate_attributions[second, item],
                )
            )
    return float(np.mean(jaccard)), float(np.mean(rho))


def unit_model(run_root: Path, seed: int, name: str) -> None:
    _, ckpt, raw = _paths(run_root)
    output_json = raw / f"model_seed{seed}_{name}.json"
    output_npz = ckpt / f"model_seed{seed}_{name}.npz"
    if output_json.exists() and output_npz.exists():
        return
    if name not in M.MODELS:
        raise ValueError(f"unknown model: {name}")

    started = time.time()
    features, events = _load(run_root, seed)
    z_train = features["Xtr_F"]
    z_val = features["Xval_F"]
    z_labeled = features["Xtl_F"]
    z_test = features["Xte_F"]
    starts_test = features["Xte_S"]
    y_labeled = features["ytl_w"]
    y_test = features["yte_w"]

    fitted = []
    scores_test = []
    scores_val = []
    for replicate in range(N_REP):
        model = M.fit_model(
            name, 100 * seed + replicate, z_train, z_labeled, y_labeled
        )
        fitted.append(model)
        scores_test.append(M.score(name, model, z_test))
        scores_val.append(M.score(name, model, z_val))
    scores_test = np.asarray(scores_test)
    scores_val = np.asarray(scores_val)
    mean_test = scores_test.mean(axis=0)
    mean_val = scores_val.mean(axis=0)
    threshold = float(np.quantile(mean_val, 0.99))
    validation_mean = float(mean_val.mean())
    validation_sd = float(mean_val.std() + 1e-12)
    metrics = event_metrics(mean_test, threshold, starts_test, events, len(starts_test))

    from sklearn.metrics import average_precision_score, roc_auc_score

    detected_ids = [idx for idx, value in enumerate(metrics["detected"]) if value]
    event_peak_indices: list[int] = []
    for event_id in detected_ids:
        event_windows = windows_of_event(starts_test, events[event_id])
        event_peak_indices.append(int(event_windows[np.argmax(mean_test[event_windows])]))

    event_native = np.empty((N_REP, 0, NCH), dtype=float)
    event_occlusion = np.empty((N_REP, 0, NCH), dtype=float)
    event_rows: list[dict] = []
    if event_peak_indices:
        queries = z_test[event_peak_indices]
        event_native, event_occlusion = _attribute_replicates(
            name, fitted, queries, z_train, seed + 700_001
        )
        native_mass, native_degenerate = _mean_mass(event_native)
        occlusion_mass, occlusion_degenerate = _mean_mass(event_occlusion)
        for item, event_id in enumerate(detected_ids):
            event = events[event_id]
            valid_channels = {int(event["ch"])}
            if int(event["sec"]) >= 0:
                valid_channels.add(int(event["sec"]))
            row = {
                "event_id": event_id,
                "type": event["type"],
                "primary_channel": int(event["ch"]),
                "secondary_channel": int(event["sec"]),
            }
            for label, mass, degenerate, raw_attr in (
                ("native", native_mass, native_degenerate, event_native),
                ("occlusion", occlusion_mass, occlusion_degenerate, event_occlusion),
            ):
                order = np.argsort(mass[item])[::-1]
                top3 = set(int(value) for value in order[:TOPK])
                jac, rho = _stability(raw_attr, item)
                row[label] = {
                    "hit1": int(int(order[0]) in valid_channels),
                    "hit3": int(bool(top3 & valid_channels)),
                    "primary_rank": int(np.where(order == int(event["ch"]))[0][0]) + 1,
                    "top3_jaccard": jac,
                    "spearman": rho,
                    "degenerate": bool(degenerate[item]),
                }
            event_rows.append(row)

    episodes = [tuple(values) for values in metrics["episodes"]]
    episode_peaks = np.asarray(
        [a + int(np.argmax(mean_test[a : b + 1])) for a, b in episodes], dtype=int
    )
    episode_native = np.empty((N_REP, 0, NCH), dtype=float)
    episode_occlusion = np.empty((N_REP, 0, NCH), dtype=float)
    episode_native_mass = np.empty((0, NCH), dtype=float)
    episode_occlusion_mass = np.empty((0, NCH), dtype=float)
    native_episode_degenerate = np.empty(0, dtype=bool)
    occlusion_episode_degenerate = np.empty(0, dtype=bool)
    peak_native_mass = np.empty((0, NCH), dtype=float)
    peak_occlusion_mass = np.empty((0, NCH), dtype=float)
    flagged_window_indices = np.empty(0, dtype=int)
    window_weights = np.empty(0, dtype=float)
    raw_window_native = np.empty((N_REP, 0, NCH), dtype=float)
    raw_window_occlusion = np.empty((N_REP, 0, NCH), dtype=float)
    if len(episode_peaks):
        flagged_window_indices = np.concatenate(
            [np.arange(first, last + 1, dtype=int) for first, last in episodes]
        )
        raw_window_native, raw_window_occlusion = _attribute_replicates(
            name,
            fitted,
            z_test[flagged_window_indices],
            z_train,
            seed + 1_400_009,
        )
        window_weights = _tail_surprisal(
            mean_test[flagged_window_indices], mean_val
        )
        (
            episode_native,
            episode_native_mass,
            native_episode_degenerate,
        ) = _aggregate_episode_attributions(
            raw_window_native, episodes, window_weights
        )
        (
            episode_occlusion,
            episode_occlusion_mass,
            occlusion_episode_degenerate,
        ) = _aggregate_episode_attributions(
            raw_window_occlusion, episodes, window_weights
        )
        peak_positions = []
        cursor = 0
        for (first, last), peak in zip(episodes, episode_peaks):
            peak_positions.append(cursor + int(peak - first))
            cursor += last - first + 1
        peak_native_mass, _ = _mean_mass(raw_window_native[:, peak_positions])
        peak_occlusion_mass, _ = _mean_mass(
            raw_window_occlusion[:, peak_positions]
        )

    episode_rows: list[dict] = []
    episode_tail_surprisal = _tail_surprisal(mean_test[episode_peaks], mean_val)
    for episode_id, episode in enumerate(episodes):
        a, b = episode
        event_ids = _episode_event_ids(episode, starts_test, events)
        native_jac, native_rho = _stability(episode_native, episode_id)
        occlusion_jac, occlusion_rho = _stability(episode_occlusion, episode_id)
        episode_rows.append(
            {
                "episode_id": episode_id,
                "window_start": int(a),
                "window_end": int(b),
                "sample_start": int(starts_test[a]),
                "sample_end": int(starts_test[b] + 20),
                "peak_window": int(episode_peaks[episode_id]),
                "peak_sample": int(starts_test[episode_peaks[episode_id]]),
                "score_raw": float(mean_test[episode_peaks[episode_id]]),
                "score_z_validation": float(
                    (mean_test[episode_peaks[episode_id]] - validation_mean)
                    / validation_sd
                ),
                "score_tail_surprisal": float(
                    episode_tail_surprisal[episode_id]
                ),
                "event_ids": event_ids,
                "native_mass": episode_native_mass[episode_id].tolist(),
                "occlusion_mass": episode_occlusion_mass[episode_id].tolist(),
                "native_peak_mass": peak_native_mass[episode_id].tolist(),
                "occlusion_peak_mass": peak_occlusion_mass[episode_id].tolist(),
                "native_degenerate": bool(native_episode_degenerate[episode_id]),
                "occlusion_degenerate": bool(occlusion_episode_degenerate[episode_id]),
                "native_top3_jaccard": native_jac,
                "native_spearman": native_rho,
                "occlusion_top3_jaccard": occlusion_jac,
                "occlusion_spearman": occlusion_rho,
            }
        )

    per_type: dict[str, dict[str, float]] = {}
    nominal = y_test == 0
    for fault_type in sorted({event["type"] for event in events}):
        indices = np.concatenate(
            [
                windows_of_event(starts_test, event)
                for event in events
                if event["type"] == fault_type
            ]
        )
        mask = nominal.copy()
        mask[indices] = True
        labels = np.zeros(len(y_test), dtype=int)
        labels[indices] = 1
        type_event_ids = [
            idx for idx, event in enumerate(events) if event["type"] == fault_type
        ]
        per_type[fault_type] = {
            "auroc": float(roc_auc_score(labels[mask], mean_test[mask])),
            "event_recall": float(
                np.mean([metrics["detected"][idx] for idx in type_event_ids])
            ),
        }

    _atomic_npz(
        output_npz,
        mean_test=mean_test,
        mean_val=mean_val,
        threshold=np.asarray(threshold),
        event_detected=np.asarray(metrics["detected"], dtype=bool),
        event_native=event_native,
        event_occlusion=event_occlusion,
        episode_native=episode_native,
        episode_occlusion=episode_occlusion,
        episode_native_mass=episode_native_mass,
        episode_occlusion_mass=episode_occlusion_mass,
        episode_native_peak_mass=peak_native_mass,
        episode_occlusion_peak_mass=peak_occlusion_mass,
        episode_peak=episode_peaks,
        flagged_window_indices=flagged_window_indices,
        window_tail_weights=window_weights,
        raw_window_native=raw_window_native,
        raw_window_occlusion=raw_window_occlusion,
    )
    payload = {
        "schema_version": 3,
        "seed": seed,
        "model": name,
        "family": M.FAMILY[name],
        "threshold_source": "nominal_validation_q0.99",
        "ranking_magnitude_source": "nominal_validation_conformal_tail_surprisal",
        "threshold": threshold,
        "validation_score_mean": validation_mean,
        "validation_score_sd": validation_sd,
        "auroc": float(roc_auc_score(y_test, mean_test)),
        "average_precision": float(average_precision_score(y_test, mean_test)),
        "episode_precision": metrics["prec_ev"],
        "event_recall": metrics["rec_ev"],
        "event_f1": metrics["f1_ev"],
        "point_adjusted_f1": metrics["f1_pa"],
        "n_episodes": metrics["n_episodes"],
        "n_events": len(events),
        "n_detected_events": len(detected_ids),
        "per_type": per_type,
        "event_explanations": event_rows,
        "episodes": episode_rows,
        "runtime_seconds": time.time() - started,
    }
    _atomic_json(output_json, payload)


def unit_cross(run_root: Path, seed: int) -> None:
    _, ckpt, raw = _paths(run_root)
    output = raw / f"cross_seed{seed}.json"
    if output.exists():
        return
    masses: dict[str, np.ndarray] = {}
    detected: dict[str, np.ndarray] = {}
    for name in M.MODELS:
        path = ckpt / f"model_seed{seed}_{name}.npz"
        if not path.exists():
            raise FileNotFoundError(f"model checkpoint missing: {path}")
        with np.load(path) as values:
            raw_native = values["event_native"]
            mean_native, _ = _mean_mass(raw_native)
            masses[name] = mean_native
            detected[name] = values["event_detected"]
    pairs: dict[str, dict | None] = {}
    for first_id, first in enumerate(M.MODELS):
        for second in M.MODELS[first_id + 1 :]:
            shared_event_ids = np.where(detected[first] & detected[second])[0]
            if not len(shared_event_ids):
                pairs[f"{first}|{second}"] = None
                continue
            first_detected_ids = np.where(detected[first])[0]
            second_detected_ids = np.where(detected[second])[0]
            first_lookup = {event_id: idx for idx, event_id in enumerate(first_detected_ids)}
            second_lookup = {
                event_id: idx for idx, event_id in enumerate(second_detected_ids)
            }
            jaccard = [
                topk_jaccard(
                    masses[first][first_lookup[event_id]],
                    masses[second][second_lookup[event_id]],
                    TOPK,
                )
                for event_id in shared_event_ids
            ]
            pairs[f"{first}|{second}"] = {
                "top3_jaccard": float(np.mean(jaccard)),
                "n_shared_events": int(len(shared_event_ids)),
            }
    _atomic_json(output, {"schema_version": 3, "seed": seed, "pairs": pairs})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--amplitude-scale", type=float, default=1.0)
    parser.add_argument("unit")
    args = parser.parse_args()
    parts = args.unit.split(":")
    if parts[0] == "gen" and len(parts) == 2:
        unit_generate(args.run_root, int(parts[1]), args.amplitude_scale)
    elif parts[0] == "feat" and len(parts) == 2:
        unit_features(args.run_root, int(parts[1]))
    elif parts[0] == "model" and len(parts) == 3:
        unit_model(args.run_root, int(parts[1]), parts[2])
    elif parts[0] == "cross" and len(parts) == 2:
        unit_cross(args.run_root, int(parts[1]))
    else:
        raise ValueError(f"invalid unit: {args.unit}")
    print(f"CRITICALITY_UNIT_OK unit={args.unit} run_root={args.run_root}")


if __name__ == "__main__":
    main()

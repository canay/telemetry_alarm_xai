"""Resumable V5 units for pooled, replicate-separated alarm queues.

Each inferential seed has shared train/validation/labelled data and seven
independent 130-orbit test trajectories.  Windowing and alarm-episode formation
occur separately inside each trajectory.  Only the resulting episode records
are pooled, with replicate-namespaced event and episode identifiers.

Operation: f07-prospective-confirmation-v5-20260828
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))

from criticality_generator_v5 import (  # noqa: E402
    EVENTS_PER_REPLICATE,
    N_TEST_REPLICATES,
    generate_seed_v5,
)
import models as M  # noqa: E402
import run_criticality_unit as v4_unit  # noqa: E402


def _master_path(run_root: Path, seed: int) -> Path:
    return run_root / "data" / f"telemetry_seed{seed}.npz"


def _rep_root(run_root: Path, replicate: int) -> Path:
    return run_root / "replicates" / f"r{replicate}"


def _model_index(name: str) -> int:
    return list(M.MODELS).index(name)


def unit_generate(run_root: Path, seed: int, amplitude_scale: float = 1.0) -> None:
    output = _master_path(run_root, seed)
    if output.exists():
        with np.load(output) as dataset:
            observed = float(dataset["amplitude_scale"])
            replicates = int(dataset["n_test_replicates"])
        if not np.isclose(observed, amplitude_scale, rtol=0.0, atol=1e-12):
            raise RuntimeError("existing V5 amplitude scale mismatch")
        if replicates != N_TEST_REPLICATES:
            raise RuntimeError("existing V5 test-replicate count mismatch")
        return
    temporary = output.with_suffix(".tmp.npz")
    generate_seed_v5(seed, temporary, amplitude_scale=amplitude_scale)
    os.replace(temporary, output)


def _materialize_replicate(run_root: Path, seed: int, replicate: int) -> Path:
    source = _master_path(run_root, seed)
    if not source.exists():
        raise FileNotFoundError(source)
    root = _rep_root(run_root, replicate)
    output = root / "data" / f"telemetry_seed{seed}.npz"
    if output.exists():
        return root
    with np.load(source) as dataset:
        payload = {
            "Xtr": dataset["Xtr"],
            "Xval": dataset["Xval"],
            "Xtl": dataset["Xtl"],
            "ytl": dataset["ytl"],
            "Xte": dataset[f"Xte_r{replicate}"],
            "yte": dataset[f"yte_r{replicate}"],
            "Xte_nominal": dataset[f"Xte_nominal_r{replicate}"],
            "mtr": dataset["mtr"],
            "mval": dataset["mval"],
            "mte": dataset[f"mte_r{replicate}"],
            "ev_tl": dataset["ev_tl"],
            "ev_te": dataset[f"ev_te_r{replicate}"],
            "train_sigma": dataset["train_sigma"],
            "schema_version": np.array(5, dtype=np.int64),
            "amplitude_scale": dataset["amplitude_scale"],
            "test_replicate": np.array(replicate, dtype=np.int64),
        }
    v4_unit._atomic_npz(output, **payload)
    return root


def unit_features(run_root: Path, seed: int) -> None:
    for replicate in range(N_TEST_REPLICATES):
        root = _materialize_replicate(run_root, seed, replicate)
        v4_unit.unit_features(root, seed)


def _run_replicate_model(
    run_root: Path, seed: int, replicate: int, name: str
) -> None:
    root = _rep_root(run_root, replicate)
    original_fit = M.fit_model
    original_attribute = v4_unit._attribute_replicates
    fit_counter = 0

    def seeded_fit(model_name, ignored_seed, z_train, z_labeled, y_labeled):
        nonlocal fit_counter
        # The fitted model set is shared across all test trajectories.  The
        # test-replicate identity must therefore not enter the fit RNG.
        derived = np.random.SeedSequence(
            [seed, _model_index(name), fit_counter, 501]
        ).generate_state(1, dtype=np.uint32)[0]
        fit_counter += 1
        return original_fit(
            model_name, int(derived), z_train, z_labeled, y_labeled
        )

    def seeded_attributes(model_name, models, queries, background, purpose_seed):
        purpose = int(purpose_seed) - seed
        native = []
        occlusion = []
        for model_replicate, model in enumerate(models):
            native.append(M.native_attr(model_name, model, queries, background))
            stream = np.random.SeedSequence(
                [
                    seed,
                    replicate,
                    _model_index(name),
                    purpose,
                    model_replicate,
                    907,
                ]
            )
            occlusion.append(
                M.occlusion_attr(
                    model_name,
                    model,
                    queries,
                    background,
                    np.random.default_rng(stream),
                )
            )
        return np.asarray(native), np.asarray(occlusion)

    M.fit_model = seeded_fit
    v4_unit._attribute_replicates = seeded_attributes
    try:
        v4_unit.unit_model(root, seed, name)
    finally:
        M.fit_model = original_fit
        v4_unit._attribute_replicates = original_attribute


def _merge_model(run_root: Path, seed: int, name: str, started: float) -> None:
    payloads = []
    artifacts = []
    y_true = []
    scores = []
    for replicate in range(N_TEST_REPLICATES):
        root = _rep_root(run_root, replicate)
        payloads.append(
            json.loads(
                (root / "raw" / f"model_seed{seed}_{name}.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        artifacts.append(root / "ckpt" / f"model_seed{seed}_{name}.npz")
        with np.load(root / "ckpt" / f"feat_seed{seed}.npz") as features:
            y_true.append(features["yte_w"])
        with np.load(artifacts[-1]) as artifact:
            scores.append(artifact["mean_test"])

    thresholds = np.asarray([row["threshold"] for row in payloads], dtype=float)
    if not np.allclose(thresholds, thresholds[0], rtol=0.0, atol=1e-12):
        raise RuntimeError(f"validation threshold drift seed={seed} model={name}")

    episode_rows = []
    event_rows = []
    pooled_episode_id = 0
    for replicate, payload in enumerate(payloads):
        event_offset = replicate * EVENTS_PER_REPLICATE
        for row in payload["event_explanations"]:
            transformed = dict(row)
            transformed["replicate"] = replicate
            transformed["local_event_id"] = int(row["event_id"])
            transformed["event_id"] = event_offset + int(row["event_id"])
            event_rows.append(transformed)
        for local_episode_id, row in enumerate(payload["episodes"]):
            transformed = dict(row)
            transformed["replicate"] = replicate
            transformed["local_episode_id"] = local_episode_id
            transformed["episode_uid"] = f"s{seed}:r{replicate}:e{local_episode_id}"
            transformed["episode_id"] = pooled_episode_id
            transformed["event_ids"] = [
                event_offset + int(value) for value in row["event_ids"]
            ]
            episode_rows.append(transformed)
            pooled_episode_id += 1

    def arrays(key: str) -> list[np.ndarray]:
        result = []
        for path in artifacts:
            with np.load(path) as artifact:
                result.append(artifact[key])
        return result

    output_npz = run_root / "ckpt" / f"model_seed{seed}_{name}.npz"
    v4_unit._atomic_npz(
        output_npz,
        event_detected=np.concatenate(arrays("event_detected"), axis=0),
        event_native=np.concatenate(arrays("event_native"), axis=1),
        event_occlusion=np.concatenate(arrays("event_occlusion"), axis=1),
        episode_native=np.concatenate(arrays("episode_native"), axis=1),
        episode_occlusion=np.concatenate(arrays("episode_occlusion"), axis=1),
        episode_native_mass=np.concatenate(arrays("episode_native_mass"), axis=0),
        episode_occlusion_mass=np.concatenate(
            arrays("episode_occlusion_mass"), axis=0
        ),
        threshold=thresholds,
        per_replicate_episode_count=np.asarray(
            [len(row["episodes"]) for row in payloads], dtype=np.int64
        ),
    )
    combined_scores = np.concatenate(scores)
    combined_labels = np.concatenate(y_true)
    output_json = run_root / "raw" / f"model_seed{seed}_{name}.json"
    v4_unit._atomic_json(
        output_json,
        {
            "schema_version": 5,
            "seed": seed,
            "model": name,
            "family": M.FAMILY[name],
            "test_replicates": N_TEST_REPLICATES,
            "test_orbits_per_replicate": 130,
            "pooling_unit": "episode_records_after_within_replicate_segmentation",
            "raw_trajectory_concatenation": False,
            "threshold_source": "shared_nominal_validation_q0.99",
            "ranking_magnitude_source": "shared_nominal_validation_conformal_tail_surprisal",
            "threshold": float(thresholds[0]),
            "validation_score_mean": payloads[0]["validation_score_mean"],
            "validation_score_sd": payloads[0]["validation_score_sd"],
            "auroc": float(roc_auc_score(combined_labels, combined_scores)),
            "average_precision": float(
                average_precision_score(combined_labels, combined_scores)
            ),
            "n_episodes": len(episode_rows),
            "per_replicate_episode_count": [
                len(row["episodes"]) for row in payloads
            ],
            "n_events": EVENTS_PER_REPLICATE * N_TEST_REPLICATES,
            "n_detected_events": int(
                sum(row["n_detected_events"] for row in payloads)
            ),
            "per_replicate_detection_metrics": [
                {
                    "replicate": replicate,
                    "auroc": row["auroc"],
                    "average_precision": row["average_precision"],
                    "episode_precision": row["episode_precision"],
                    "event_recall": row["event_recall"],
                    "event_f1": row["event_f1"],
                    "point_adjusted_f1": row["point_adjusted_f1"],
                    "n_episodes": row["n_episodes"],
                }
                for replicate, row in enumerate(payloads)
            ],
            "event_explanations": event_rows,
            "episodes": episode_rows,
            "runtime_seconds": time.time() - started,
        },
    )


def unit_model(run_root: Path, seed: int, name: str) -> None:
    output_json = run_root / "raw" / f"model_seed{seed}_{name}.json"
    output_npz = run_root / "ckpt" / f"model_seed{seed}_{name}.npz"
    if output_json.exists() and output_npz.exists():
        return
    if name not in M.MODELS:
        raise ValueError(f"unknown model: {name}")
    started = time.time()
    for replicate in range(N_TEST_REPLICATES):
        _run_replicate_model(run_root, seed, replicate, name)
    _merge_model(run_root, seed, name, started)


def unit_cross(run_root: Path, seed: int) -> None:
    v4_unit.unit_cross(run_root, seed)
    output = run_root / "raw" / f"cross_seed{seed}.json"
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["schema_version"] = 5
    payload["test_replicates"] = N_TEST_REPLICATES
    v4_unit._atomic_json(output, payload)


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
        raise ValueError(f"invalid V5 unit: {args.unit}")
    print(f"CRITICALITY_V5_UNIT_OK unit={args.unit} run_root={args.run_root}")


if __name__ == "__main__":
    main()

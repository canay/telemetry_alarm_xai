"""Prospective V5 generator with seven independent test trajectories per seed.

The first eight ``SeedSequence`` children are identical to V4.  Test replicate
zero therefore reproduces the V4 test stream, while children 8--25 add six
independent 130-orbit test trajectories without changing training, validation,
or labelled-development data.

Operation: f07-prospective-confirmation-v5-20260828
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from criticality_generator import inject_anomalies_v2
from telemetry_generator import generate_nominal


N_TEST_REPLICATES = 7
TEST_ORBITS_PER_REPLICATE = 130
EVENTS_PER_REPLICATE = 36


def generate_seed_v5(seed: int, output: Path, *, amplitude_scale: float = 1.0) -> None:
    streams = np.random.SeedSequence(seed).spawn(5 + 3 * N_TEST_REPLICATES)
    rng_train, rng_val, rng_labeled_nominal, rng_labeled_fault = (
        np.random.default_rng(stream) for stream in streams[:4]
    )
    rng_labeled_target = np.random.default_rng(streams[4])

    x_train, mode_train, _ = generate_nominal(60, rng_train)
    x_val, mode_val, _ = generate_nominal(30, rng_val)
    sigma = x_train.std(axis=0)
    x_labeled_nominal, mode_labeled, _ = generate_nominal(
        130, rng_labeled_nominal
    )
    x_labeled, y_labeled, events_labeled = inject_anomalies_v2(
        x_labeled_nominal,
        mode_labeled,
        rng_labeled_fault,
        n_per_type=6,
        sigma=sigma,
        amplitude_scale=amplitude_scale,
        target_rng=rng_labeled_target,
    )

    payload: dict[str, np.ndarray | str] = {
        "Xtr": x_train.astype(np.float32),
        "Xval": x_val.astype(np.float32),
        "Xtl": x_labeled.astype(np.float32),
        "ytl": y_labeled,
        "mtr": mode_train,
        "mval": mode_val,
        "ev_tl": json.dumps(events_labeled),
        "train_sigma": sigma.astype(np.float64),
        "schema_version": np.array(5, dtype=np.int64),
        "amplitude_scale": np.array(amplitude_scale, dtype=np.float64),
        "n_test_replicates": np.array(N_TEST_REPLICATES, dtype=np.int64),
        "test_orbits_per_replicate": np.array(
            TEST_ORBITS_PER_REPLICATE, dtype=np.int64
        ),
    }
    test_stream_triples = tuple(
        (5 + 3 * replicate, 6 + 3 * replicate, 7 + 3 * replicate)
        for replicate in range(N_TEST_REPLICATES)
    )
    for replicate, (nominal_id, fault_id, target_id) in enumerate(
        test_stream_triples
    ):
        x_test_nominal, mode_test, _ = generate_nominal(
            TEST_ORBITS_PER_REPLICATE, np.random.default_rng(streams[nominal_id])
        )
        x_test, y_test, events_test = inject_anomalies_v2(
            x_test_nominal,
            mode_test,
            np.random.default_rng(streams[fault_id]),
            n_per_type=6,
            sigma=sigma,
            amplitude_scale=amplitude_scale,
            target_rng=np.random.default_rng(streams[target_id]),
        )
        if len(events_test) != EVENTS_PER_REPLICATE:
            raise RuntimeError(
                f"unexpected event count seed={seed} replicate={replicate}: "
                f"{len(events_test)}"
            )
        for local_id, event in enumerate(events_test):
            event["replicate"] = replicate
            event["local_event_id"] = local_id
            event["event_id"] = replicate * EVENTS_PER_REPLICATE + local_id
        payload[f"Xte_r{replicate}"] = x_test.astype(np.float32)
        payload[f"yte_r{replicate}"] = y_test
        payload[f"Xte_nominal_r{replicate}"] = x_test_nominal.astype(np.float32)
        payload[f"mte_r{replicate}"] = mode_test
        payload[f"ev_te_r{replicate}"] = json.dumps(events_test)

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, **payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed", type=int)
    parser.add_argument("output", type=Path)
    parser.add_argument("--amplitude-scale", type=float, default=1.0)
    args = parser.parse_args()
    generate_seed_v5(args.seed, args.output, amplitude_scale=args.amplitude_scale)
    print(f"CRITICALITY_V5_SEED_OK seed={args.seed} output={args.output}")


if __name__ == "__main__":
    main()

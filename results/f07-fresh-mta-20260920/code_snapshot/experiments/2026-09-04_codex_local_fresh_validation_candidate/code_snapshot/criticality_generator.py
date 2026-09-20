"""Criticality-uplift generator with type-independent target event impact.

This module leaves the historical generator untouched.  It reuses the nominal
LEO telemetry process but records fault-specific parameters and the realised
standardised deviation from the counterfactual nominal stream for every event.
Each fault receives a target standardized impact from an independent RNG stream
and its raw perturbation is rescaled to that target.  This preserves the fault's
temporal/channel pattern while preventing impact magnitude from acting as a
surrogate fault-type label.  Mission criticality is applied later.

Operation: f07-criticality-conditioned-uplift-20260826
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from telemetry_generator import (
    ANOM_TYPES,
    DUR,
    ELIGIBLE,
    N_PER_ORBIT,
    RUNAWAY_SECONDARY,
    SENSOR_FLOOR,
    _ar1,
    generate_nominal,
)


def _event_impact(before: np.ndarray, after: np.ndarray, sigma: np.ndarray) -> tuple[float, list[float]]:
    scaled = np.abs(after - before) / np.maximum(sigma[None, :], 1e-9)
    by_channel = scaled.mean(axis=0)
    return float(by_channel.sum()), [float(v) for v in by_channel]


def inject_anomalies_v2(
    nominal: np.ndarray,
    mode: np.ndarray,
    rng: np.random.Generator,
    *,
    n_per_type: int = 6,
    sigma: np.ndarray | None = None,
    gap: int = 40,
    amplitude_scale: float = 1.0,
    target_rng: np.random.Generator | None = None,
    target_impact_range: tuple[float, float] = (0.75, 5.0),
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Inject non-overlapping faults at type-independent target impacts."""

    n = nominal.shape[0]
    faulty = nominal.copy()
    labels = np.zeros(n, dtype=int)
    sigma = nominal.std(axis=0) if sigma is None else np.asarray(sigma, dtype=float)
    target_rng = rng if target_rng is None else target_rng
    occupied = np.zeros(n, dtype=bool)
    events: list[dict] = []
    order = [fault_type for fault_type in ANOM_TYPES for _ in range(n_per_type)]
    rng.shuffle(order)

    for fault_type in order:
        duration = int(rng.integers(*DUR[fault_type]))
        for _ in range(300):
            start = int(rng.integers(N_PER_ORBIT, n - duration - N_PER_ORBIT))
            left = max(0, start - gap)
            right = min(n, start + duration + gap)
            if not occupied[left:right].any():
                break
        else:
            continue

        end = start + duration
        channel = int(rng.choice(ELIGIBLE[fault_type]))
        secondary = -1
        params: dict[str, float | int] = {"amplitude_scale": float(amplitude_scale)}
        before = nominal[start:end].copy()

        if fault_type == "stuck":
            faulty[start:end, channel] = faulty[start, channel]
            params["held_value"] = float(faulty[start, channel])
        elif fault_type == "dropout":
            dropout_rate = float(rng.uniform(0.30, 0.85))
            idx = start + np.where(rng.random(duration) < dropout_rate)[0]
            if not len(idx):
                idx = np.asarray([start + int(rng.integers(0, duration))])
            faulty[idx, channel] = SENSOR_FLOOR[channel]
            params["dropout_rate"] = dropout_rate
            params["dropout_count"] = int(len(idx))
        elif fault_type == "bias":
            magnitude_sigma = float(rng.uniform(1.5, 6.0) * amplitude_scale)
            sign = int(rng.choice([-1, 1]))
            faulty[start:end, channel] += sign * magnitude_sigma * sigma[channel]
            params["magnitude_sigma"] = magnitude_sigma
            params["sign"] = sign
        elif fault_type == "drift":
            terminal_sigma = float(rng.uniform(1.5, 8.0) * amplitude_scale)
            sign = int(rng.choice([-1, 1]))
            faulty[start:end, channel] += (
                sign * terminal_sigma * sigma[channel] * np.linspace(0.0, 1.0, duration)
            )
            params["terminal_sigma"] = terminal_sigma
            params["sign"] = sign
        elif fault_type == "coupling":
            replacement_fraction = float(rng.uniform(0.30, 1.0) * amplitude_scale)
            replacement_fraction = min(1.0, replacement_fraction)
            mu = nominal[start:end, channel].mean()
            sd = nominal[start:end, channel].std() + 1e-6
            z = _ar1(rng, duration, 0.97, 1.0)
            z = (z - z.mean()) / (z.std() + 1e-9)
            replacement = mu + sd * z
            faulty[start:end, channel] = (
                (1.0 - replacement_fraction) * faulty[start:end, channel]
                + replacement_fraction * replacement
            )
            params["replacement_fraction"] = replacement_fraction
        elif fault_type == "runaway":
            secondary = int(RUNAWAY_SECONDARY[channel])
            primary_sigma = float(rng.uniform(2.0, 8.0) * amplitude_scale)
            secondary_sigma = float(rng.uniform(1.0, 4.0) * amplitude_scale)
            tau_ratio = float(rng.uniform(2.5, 4.0))
            rise = np.exp(np.arange(duration) / (duration / tau_ratio)) - 1.0
            rise /= max(rise[-1], 1e-12)
            faulty[start:end, channel] += primary_sigma * sigma[channel] * rise
            faulty[start:end, secondary] += secondary_sigma * sigma[secondary] * rise
            params["primary_terminal_sigma"] = primary_sigma
            params["secondary_terminal_sigma"] = secondary_sigma
            params["tau_ratio"] = tau_ratio

        raw_after = faulty[start:end].copy()
        raw_impact, _ = _event_impact(before, raw_after, sigma)
        if raw_impact <= 1e-12:
            raise RuntimeError(f"degenerate raw perturbation for {fault_type}")
        target_impact = float(
            target_rng.uniform(*target_impact_range) * amplitude_scale
        )
        realisation_scale = target_impact / raw_impact
        faulty[start:end] = before + (raw_after - before) * realisation_scale
        after = faulty[start:end]
        impact, impact_by_channel = _event_impact(before, after, sigma)
        params["raw_impact"] = float(raw_impact)
        params["target_impact"] = target_impact
        params["realisation_scale"] = float(realisation_scale)
        occupied[start:end] = True
        labels[start:end] = 1
        events.append(
            {
                "type": fault_type,
                "ch": channel,
                "sec": secondary,
                "start": start,
                "end": end,
                "duration": duration,
                "mode": int(mode[start]),
                "impact": impact,
                "impact_by_channel": impact_by_channel,
                "params": params,
            }
        )

    return faulty, labels, events


def generate_seed_v2(seed: int, output: Path, *, amplitude_scale: float = 1.0) -> None:
    streams = np.random.SeedSequence(seed).spawn(8)
    rng_train, rng_val, rng_labeled_nominal, rng_labeled_fault = (
        np.random.default_rng(stream) for stream in streams[:4]
    )
    rng_labeled_target, rng_test_nominal, rng_test_fault, rng_test_target = (
        np.random.default_rng(stream) for stream in streams[4:]
    )
    x_train, mode_train, _ = generate_nominal(60, rng_train)
    x_val, mode_val, _ = generate_nominal(30, rng_val)
    sigma = x_train.std(axis=0)
    x_labeled_nominal, mode_labeled, _ = generate_nominal(130, rng_labeled_nominal)
    x_labeled, y_labeled, events_labeled = inject_anomalies_v2(
        x_labeled_nominal,
        mode_labeled,
        rng_labeled_fault,
        n_per_type=6,
        sigma=sigma,
        amplitude_scale=amplitude_scale,
        target_rng=rng_labeled_target,
    )
    x_test_nominal, mode_test, _ = generate_nominal(130, rng_test_nominal)
    x_test, y_test, events_test = inject_anomalies_v2(
        x_test_nominal,
        mode_test,
        rng_test_fault,
        n_per_type=6,
        sigma=sigma,
        amplitude_scale=amplitude_scale,
        target_rng=rng_test_target,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        Xtr=x_train.astype(np.float32),
        Xval=x_val.astype(np.float32),
        Xtl=x_labeled.astype(np.float32),
        ytl=y_labeled,
        Xte=x_test.astype(np.float32),
        yte=y_test,
        Xte_nominal=x_test_nominal.astype(np.float32),
        mtr=mode_train,
        mval=mode_val,
        mte=mode_test,
        ev_tl=json.dumps(events_labeled),
        ev_te=json.dumps(events_test),
        train_sigma=sigma.astype(np.float64),
        schema_version=np.array(3, dtype=np.int64),
        amplitude_scale=np.array(amplitude_scale, dtype=np.float64),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed", type=int)
    parser.add_argument("output", type=Path)
    parser.add_argument("--amplitude-scale", type=float, default=1.0)
    args = parser.parse_args()
    generate_seed_v2(args.seed, args.output, amplitude_scale=args.amplitude_scale)
    print(f"CRITICALITY_SEED_OK seed={args.seed} output={args.output}")


if __name__ == "__main__":
    main()

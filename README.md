# From salience to decisions: A scenario-conditioned benchmark for explainable spacecraft-telemetry alarm review

Curated replication and public-freeze package for the study “From salience to decisions: A scenario-conditioned benchmark for explainable spacecraft-telemetry alarm review.”

This repository separates anomaly detection, fault-channel salience, explanation stability, and operational alarm-review utility over aligned episodes. Release `v1.1.0` froze, before any confirmatory generation, the exact V4 scenario-heterogeneity protocol, code, seed range, five-condition decision rule, null calibrations, joint-power calculation, and provenance driver. The bundled V3 outputs are explicitly exploratory; they are not confirmatory evidence.

Release `v1.2.0` publishes the outcome without changing that freeze. The seeds 10--29 replication stopped before policy or null endpoint analysis because seed 12 isolation forest produced 9 alarm episodes against the preregistered minimum of 10. The property suite passed 1,248 of 1,249 checks, the run closed as `NOT_CONFIRMED_PROPERTY_GATE`, and no threshold reduction, replacement seed, model exclusion, or other rescue was performed. The result therefore reports an analyzability failure, not a zero effect and not a successful replication.

The package also contains bounded transfer checks on OpenML 40900, KDDCup99, and OPSSAT-AD. These datasets support detection or within-model feature-signature repeatability only; they do not establish spacecraft fault-channel attribution correctness or operational deployment validity.

## Contents

- `code/`: synthetic telemetry generation, resumable detector work units, aggregation, statistical analyses, transfer checks, and figure scripts.
- `results/`: frozen JSON/CSV outputs used by the study, including primary synthetic results, ten-seed sensitivity analyses, KDDCup99 audit-rerun results, and OPSSAT-AD results.
- `data/README.md`: dataset acquisition and redistribution boundaries. Third-party datasets and generated caches are not bundled.
- `REPRODUCE.md`: environment setup and reproduction commands.
- `ARTIFACTS.md`: claim-to-artifact map and scope limitations.
- `PROTOCOL_V1_1.md`: human-readable public-frozen confirmation protocol.
- `CONFIRMATORY_PLAN.json`: machine-readable required files, hashes, seeds, models, endpoints, and decision method.
- `POWER_PLAN_V4.json`: deterministic joint-power design artifact.
- `code/run_confirmation_v4.py`: remote-tag-bound driver that refuses pre-release or unregistered artifacts.
- `results/scenario_utility_v1_2/`: exploratory manuscript aggregates, model-level figure, and the preregistered replication property-gate closure.
- `checksums.sha256`: SHA-256 inventory for the released payload.

## Quick verification

```bash
python smoke_check.py
```

The smoke check validates the required artifact inventory, parses every Python source file, and reads the principal JSON summaries. It does not rerun the compute-intensive experiments.

## Frozen confirmation

Only after the `v1.1.0` release exists, run from the repository root with a new or empty output directory outside this checkout:

```bash
python code/run_confirmation_v4.py \
  --release-root . \
  --run-root ../criticality_confirmation_v4 \
  --max-workers 2
```

The driver verifies the remote GitHub tag commit, release publication time, release-body plan hash, clean checkout, complete frozen-file hash set, amplitude scale, and every resumable artifact. A nonzero final exit can be a valid `NOT_CONFIRMED` scientific outcome; inspect `metrics/confirmatory_failure.json` or `metrics/confirmatory_decision.json`, depending on which frozen gate closed the run.

## Full reproduction

See `REPRODUCE.md`. The synthetic data are generated deterministically from fixed seeds. External datasets remain at their original sources and are downloaded or fetched by the documented steps.

## License

The original code and package documentation in this repository are released under the MIT License. Third-party datasets are not relicensed here and remain governed by their source records.

## Citation

See `CITATION.cff`.

## Release provenance

Updated: 2026-08-26 18:28 +03:00
Tool: Codex
Model: GPT-5
Operation ID: `f07-scenario-utility-results-release-20260826`

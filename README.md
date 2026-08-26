# Beyond anomaly scores: An episode-aligned evaluation framework for explainable alarm triage in spacecraft telemetry

Curated replication and public-freeze package for the study “Beyond anomaly scores: An episode-aligned evaluation framework for explainable alarm triage in spacecraft telemetry.”

This repository separates anomaly detection, fault-channel salience, explanation stability, and operational alarm-review utility over aligned episodes. Release `v1.1.0` additionally freezes, before any confirmatory generation, the exact V4 scenario-heterogeneity protocol, code, seed range, five-condition decision rule, null calibrations, joint-power calculation, and provenance driver. The bundled V3 outputs are explicitly exploratory; they are not confirmatory evidence.

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

The driver verifies the remote GitHub tag commit, release publication time, release-body plan hash, clean checkout, complete frozen-file hash set, amplitude scale, and every resumable artifact. A nonzero final exit can be a valid `NOT_CONFIRMED` scientific outcome; inspect `metrics/confirmatory_decision.json`.

## Full reproduction

See `REPRODUCE.md`. The synthetic data are generated deterministically from fixed seeds. External datasets remain at their original sources and are downloaded or fetched by the documented steps.

## License

The original code and package documentation in this repository are released under the MIT License. Third-party datasets are not relicensed here and remain governed by their source records.

## Citation

See `CITATION.cff`.

## Release provenance

Prepared: 2026-08-26 17:57 +03:00  
Tool: Codex  
Model: GPT-5  
Operation ID: `f07-criticality-v4-pre-freeze-repair-20260826`

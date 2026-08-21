# Reliability-Aware Explainable Alarm Triage for Spacecraft Telemetry

Curated replication package for the study “Reliability-Aware Explainable Alarm Triage for Spacecraft Telemetry: Separating Detection, Salience, Stability, and Priority.”

This repository contains the analysis code and frozen result artifacts used to evaluate four distinct layers: anomaly detection, fault-channel salience, explanation stability, and severity-aware alarm prioritization. The package also contains bounded transfer checks on OpenML 40900, KDDCup99, and OPSSAT-AD. These transfer datasets support detection or within-model feature-signature repeatability only; they do not establish spacecraft fault-channel attribution correctness or operational deployment validity.

## Contents

- `code/`: synthetic telemetry generation, resumable detector work units, aggregation, statistical analyses, transfer checks, and figure scripts.
- `results/`: frozen JSON/CSV outputs used by the study, including primary synthetic results, ten-seed sensitivity analyses, KDDCup99 audit-rerun results, and OPSSAT-AD results.
- `data/README.md`: dataset acquisition and redistribution boundaries. Third-party datasets and generated caches are not bundled.
- `REPRODUCE.md`: environment setup and reproduction commands.
- `ARTIFACTS.md`: claim-to-artifact map and scope limitations.
- `checksums.sha256`: SHA-256 inventory for the released payload.

## Quick verification

```bash
python smoke_check.py
```

The smoke check validates the required artifact inventory, parses every Python source file, and reads the principal JSON summaries. It does not rerun the compute-intensive experiments.

## Full reproduction

See `REPRODUCE.md`. The synthetic data are generated deterministically from fixed seeds. External datasets remain at their original sources and are downloaded or fetched by the documented steps.

## License

The original code and package documentation in this repository are released under the MIT License. Third-party datasets are not relicensed here and remain governed by their source records.

## Citation

See `CITATION.cff`.

## Release provenance

Prepared: 2026-08-21 16:37 +03:00  
Tool: Codex  
Model: GPT-5.6  
Operation ID: `f07-public-release-g11a-20260821`

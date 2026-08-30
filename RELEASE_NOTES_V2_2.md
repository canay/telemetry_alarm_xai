# Release v2.2.0: transfer signature provenance correction

Date/time: 2026-08-30 04:08 +03:00
Tool: Codex
Model, if known: GPT-5.6
Operation ID: `f07-v5-round-d-final-corrections-20260830`

This release corrects public-package provenance for two transfer signature
layers. The corrected artifacts had already been produced and frozen on
2026-07-28 but had not been propagated into the curated `results/` tree.

- OPSSAT-AD isolation forest now uses the documented raw anomaly-score
  perturbation signature; its within-model cosine is `0.9834087765899527`
  over `10/10` valid pairs.
- KDDCup99 random forest now marks the four pairs involving its zero-norm
  signature as degenerate; its within-model cosine is
  `0.4226229954179248` over `6/10` valid pairs.
- `benchmark_results.csv`, `feature_signature_audit.csv`, and
  `signature_stability.csv` were refreshed in both transfer directories.
- Each directory now includes `signature_repair_provenance.json`, which binds
  the exact corrected artifact hashes.

No detector predictions, dataset split, scenario-utility value, V4/V5 protocol,
property-gate result, endpoint status, or scientific conclusion changed. V4 and
V5 remain terminal pre-endpoint outcomes with no rescue.

# Artifact Map

Date/time: 2026-08-21 16:37 +03:00  
Tool: Codex  
Model: GPT-5.6  
Operation ID: `f07-public-release-g11a-20260821`

| Evidence layer | Frozen artifact | Reproduction entry point | Valid interpretation |
| --- | --- | --- | --- |
| Primary synthetic detection, salience, stability, and priority summaries | `results/results_summary.json`; `results/raw/` | `code/telemetry_generator.py`, `code/run_unit.py`, `code/aggregate.py` | Controlled synthetic benchmark with known injected fault-channel labels |
| Priority sensitivity, ablation, and uncertainty | `results/q1_audit_revision/`; `results/q1_seed_expansion/` | `code/q1_audit_revision_stats.py` | Sensitivity and bounded statistical evidence; no universal priority-gain claim |
| Supervised label-budget sensitivity | `results/q1_audit_revision/label_budget_sensitivity*.csv` | `code/q1_audit_label_budget.py` | Synthetic supervised sensitivity only |
| OpenML satellite-image transfer | `results/openml_results.json` | `code/run_openml.py` | Detection/signature transfer; not spacecraft telemetry attribution |
| KDDCup99 transfer audit | `results/second_transfer_benchmark_audit_rerun/` | `code/run_second_transfer_benchmark.py` | Network-telemetry diagnostic transfer only |
| OPSSAT-AD transfer audit | `results/opssat_transfer_benchmark/` | `code/run_opssat_transfer_benchmark.py` | Real spacecraft-telemetry detection and within-model signature repeatability; not causal fault-channel correctness |

The package intentionally excludes manuscript sources, submission files, internal workflow state, private logs, generated dataset caches, and third-party dataset files.

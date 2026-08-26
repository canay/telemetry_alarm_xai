# Artifact Map

Date/time: 2026-08-26 17:57 +03:00  
Tool: Codex  
Model: GPT-5  
Operation ID: `f07-criticality-v4-pre-freeze-repair-20260826`

| Evidence layer | Frozen artifact | Reproduction entry point | Valid interpretation |
| --- | --- | --- | --- |
| Primary synthetic detection, salience, stability, and priority summaries | `results/results_summary.json`; `results/raw/` | `code/telemetry_generator.py`, `code/run_unit.py`, `code/aggregate.py` | Controlled synthetic benchmark with known injected fault-channel labels |
| Priority sensitivity, ablation, and uncertainty | `results/q1_audit_revision/`; `results/q1_seed_expansion/` | `code/q1_audit_revision_stats.py` | Sensitivity and bounded statistical evidence; no universal priority-gain claim |
| Supervised label-budget sensitivity | `results/q1_audit_revision/label_budget_sensitivity*.csv` | `code/q1_audit_label_budget.py` | Synthetic supervised sensitivity only |
| OpenML satellite-image transfer | `results/openml_results.json` | `code/run_openml.py` | Detection/signature transfer; not spacecraft telemetry attribution |
| KDDCup99 transfer audit | `results/second_transfer_benchmark_audit_rerun/` | `code/run_second_transfer_benchmark.py` | Network-telemetry diagnostic transfer only |
| OPSSAT-AD transfer audit | `results/opssat_transfer_benchmark/` | `code/run_opssat_transfer_benchmark.py` | Real spacecraft-telemetry detection and within-model signature repeatability; not causal fault-channel correctness |
| V3 scenario-utility discovery | `results/v3_discovery_*` | `code/criticality_analysis_v4.py` only for the public V4 definitions; the bundled V3 files remain historical | Exploratory design/null evidence; not confirmation |
| V4 public freeze | `PROTOCOL_V1_1.md`; `CONFIRMATORY_PLAN.json`; `POWER_PLAN_V4.json` | `code/run_confirmation_v4.py` | Outcome-blind protocol/code/provenance freeze; release contains no seeds 10--29 outcomes |

The package intentionally excludes manuscript sources, submission files, internal workflow state, private logs, generated dataset caches, and third-party dataset files.

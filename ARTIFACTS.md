# Artifact Map

Date/time: 2026-08-26 18:28 +03:00
Tool: Codex
Model: GPT-5
Operation ID: `f07-scenario-utility-results-release-20260826`

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
| V1.1 replication closure | `results/scenario_utility_v1_2/replication_property_tests.json`; `results/scenario_utility_v1_2/confirmatory_failure.json` | Frozen V4 property suite and fail-closed driver | `NOT_CONFIRMED_PROPERTY_GATE`; 1,248/1,249 checks passed; no policy/null endpoint analysis and no rescue |
| Scenario-utility manuscript support | `results/scenario_utility_v1_2/manuscript_summary.json`; `results/scenario_utility_v1_2/scenario_model_gains.*` | Exploratory seeds 0--9 frozen outputs | Exploratory raw and above-null estimates plus model heterogeneity; not confirmatory evidence |
| V5 endpoint-blind pilot | `PILOT_PROPERTY_V5.json` | `code/property_pilot_v5.py` | R=7 analyzability and nesting evidence only; no policy or endpoint evidence |
| V5 discovery-only planning | `POWER_PLAN_V5.json` | `code/power_freeze_v5.py` | Five-endpoint fixed-mean power and predictive assurance; not confirmation |
| V5 public freeze | `PROTOCOL_V2_0.md`; `CONFIRMATORY_PLAN_V5.json` | `code/run_v5_development.py`; `code/confirmatory_analysis_v5.py` | Outcome-blind V5 protocol/code/provenance freeze for untouched seeds 300--319 |
| V5 confirmation closure | `results/scenario_utility_v2_1/v5_property_tests.json`; `v5_run_manifest.json`; `v5_confirmatory_failure.json` | Frozen V5 property suite and release-bound launcher | `NOT_CONFIRMED_PROPERTY_GATE`; 3,087/3,089 checks passed; fixed gate misspecification; no endpoint analysis or rescue |

The package intentionally excludes manuscript sources, submission files, internal workflow state, private logs, generated dataset caches, and third-party dataset files.

Date/time: 2026-08-30 01:21 +03:00
Tool: Codex
Model: GPT-5
Operation ID: `f07-v5-public-freeze-20260830`

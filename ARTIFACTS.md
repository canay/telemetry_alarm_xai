# Artifact Map

Date/time: 2026-08-30 04:32 +03:00
Tool: Codex
Model: GPT-5.6
Operation ID: `f07-v2-2-1-hash-portability-20260830`

| Evidence layer | Frozen artifact | Reproduction entry point | Valid interpretation |
| --- | --- | --- | --- |
| Primary synthetic detection, salience, stability, and priority summaries | `results/results_summary.json`; `results/raw/` | `code/telemetry_generator.py`, `code/run_unit.py`, `code/aggregate.py` | Controlled synthetic benchmark with known injected fault-channel labels |
| Priority sensitivity, ablation, and uncertainty | `results/q1_audit_revision/`; `results/q1_seed_expansion/` | `code/q1_audit_revision_stats.py` | Sensitivity and bounded statistical evidence; no universal priority-gain claim |
| Supervised label-budget sensitivity | `results/q1_audit_revision/label_budget_sensitivity*.csv` | `code/q1_audit_label_budget.py` | Synthetic supervised sensitivity only |
| OpenML satellite-image transfer | `results/openml_results.json` | `code/run_openml.py` | Detection/signature transfer; not spacecraft telemetry attribution |
| KDDCup99 transfer audit | `results/second_transfer_benchmark_audit_rerun/`; `signature_repair_provenance.json` | `code/run_second_transfer_benchmark.py`; repaired LF-normalized release bytes are hash-bound in the provenance record | Network-telemetry diagnostic transfer only; zero-norm pairs are excluded from cosine summaries |
| OPSSAT-AD transfer audit | `results/opssat_transfer_benchmark/`; `signature_repair_provenance.json` | `code/run_opssat_transfer_benchmark.py`; repaired LF-normalized release bytes are hash-bound in the provenance record | Real spacecraft-telemetry detection and within-model signature repeatability; not causal fault-channel correctness |
| V3 scenario-utility discovery | `results/v3_discovery_*` | `code/criticality_analysis_v4.py` only for the public V4 definitions; the bundled V3 files remain historical | Exploratory design/null evidence; not confirmation |
| V4 public freeze | `PROTOCOL_V1_1.md`; `CONFIRMATORY_PLAN.json`; `POWER_PLAN_V4.json` | `code/run_confirmation_v4.py` | Outcome-blind protocol/code/provenance freeze; release contains no seeds 10--29 outcomes |
| V1.1 replication closure | `results/scenario_utility_v1_2/replication_property_tests.json`; `results/scenario_utility_v1_2/confirmatory_failure.json` | Frozen V4 property suite and fail-closed driver | `NOT_CONFIRMED_PROPERTY_GATE`; 1,248/1,249 checks passed; no policy/null endpoint analysis and no rescue |
| Scenario-utility manuscript support | `results/scenario_utility_v1_2/manuscript_summary.json`; `results/scenario_utility_v1_2/scenario_model_gains.*` | Exploratory seeds 0--9 frozen outputs | Exploratory raw and above-null estimates plus model heterogeneity; not confirmatory evidence |
| V5 endpoint-blind pilot | `PILOT_PROPERTY_V5.json` | `code/property_pilot_v5.py` | R=7 analyzability and nesting evidence only; no policy or endpoint evidence |
| V5 discovery-only planning | `POWER_PLAN_V5.json` | `code/power_freeze_v5.py` | Five-endpoint fixed-mean power and predictive assurance; not confirmation |
| V5 public freeze | `PROTOCOL_V2_0.md`; `CONFIRMATORY_PLAN_V5.json` | `code/run_v5_development.py`; `code/confirmatory_analysis_v5.py` | Outcome-blind V5 protocol/code/provenance freeze for untouched seeds 300--319 |
| V5 confirmation closure | `results/scenario_utility_v2_1/v5_property_tests.json`; `v5_run_manifest.json`; `v5_confirmatory_failure.json` | Frozen V5 property suite and release-bound launcher | `NOT_CONFIRMED_PROPERTY_GATE`; 3,087/3,089 checks passed; fixed gate misspecification; no endpoint analysis or rescue |

The package intentionally excludes manuscript sources, submission files, internal workflow state, private logs, generated dataset caches, and third-party dataset files.

Date/time: 2026-08-30 04:32 +03:00
Tool: Codex
Model: GPT-5.6
Operation ID: `f07-v2-2-1-hash-portability-20260830`

## Fresh MTA internal replication

Release `f07-fresh-mta-results-20260920` and `results/f07-fresh-mta-20260920/PUBLIC_RESULTS_MANIFEST.json` bind the four assets, all 4,920 scientific outputs, 400 atomic checkpoints, exact source snapshot, and 40-seed summary. `analysis/primary_contrasts.csv` contains C1–C4 with 98.75% intervals; `secondary_contrasts.csv` contains all-six-model and per-model descriptive 95% intervals. `policy_endpoints.csv` retains every policy/profile/target cell. The fresh internal replication does not reopen V4/V5 endpoints or establish external operational validity.

## Current figure and summary reproduction (2026-09-20 correction)

Date/time: 2026-09-20T23:19:20+03:00
Tool: Codex
Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920

The current five-seed summary uses sample SD (ddof=1). Pooled detector-seed
priority gains are descriptive only (five independent seeds). The earlier
public summary contained population SD and a superseded pooled Wilcoxon
result; it has been replaced from the already-saved corrected reduction.
No model was refitted. Original producer versions.txt is preserved; a new
consumer writes its own aggregation_versions.txt separately.

Run from the repository root into a new output directory:

```bash
python code/reproduce_curated_artifacts.py --output-dir rebuilt-curated
```

This verifies the full summary against the 30 saved detector/seed outputs
and five cross-model records, rebuilds signature-pair validity from saved
vectors, and renders current Figure 5 (scenario-conditioned utility) and
Figure S1 (KDD signature pairs). It uses only stored outputs; neither
training nor V4/V5 endpoint analysis runs. Floating-point comparisons use
rtol=1e-10 and atol=1e-12; rendered PDF bytes may differ by metadata/fonts.

Figure 5 inputs are in results/scenario_utility_v1_2/figure_inputs. The
original generator is code/build_criticality_manuscript_artifacts.py; its
build_figure function is used by the portable consumer. Supplement Figure
S1 uses code/plot_round_b_kdd_signature_pairs.py and the complete saved
results/signature_pair_audit tables. OPSSAT has 10 valid and zero degenerate
pairs for each model; the current stability CSV includes these counts.
Legacy figures.py option e now writes fig_legacy_ndcg_priority, preventing
an NDCG plot from overwriting current fig_prioritization.

Fresh MTA runtime pins are also supplied explicitly at
results/f07-fresh-mta-20260920/MTA_RUNTIME.json, copied byte-for-byte from the
prospective runtime record. The fresh four result archives are unchanged.

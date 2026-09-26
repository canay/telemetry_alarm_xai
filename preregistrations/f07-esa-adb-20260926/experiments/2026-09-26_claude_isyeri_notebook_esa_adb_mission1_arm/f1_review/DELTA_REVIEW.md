# F1 delta review: ESA-ADB Mission1 bounded arm, protocol v3 and code

- Review ID: F07-ESA-ADB-F1-DELTA-REVIEW
- Reviewer: claude-fable-5-1 (independent delta reviewer; not the editor)
- Reviewed at: 2026-09-26T21:29:52+03:00
- Operation: f07-rb4-esa-adb-revision-20260926
- Candidate: `ESA_ADB_PROTOCOL_CANDIDATE_V3.json`, SHA-256 `DCE48A36D693A843DE08582908907BF340DEB1E457276DB257C9179C2CB8B03A` (v2 observed `7AC751A6...`, equal to the F1 binding; F3_FACTS `CEA57739...`, equal to the protocol)
- Code to be frozen (`src/`): esa_core.py `7206F9587AC34FE2C94095EE828AE8CA328550DA75017B3A6604A0E6C1B85B24`, esa_arm.py `60D50EA9CA18867392225D5712F23C98794887C835A98EA898DD89E99D48E171`, esa_property_tests.py `78EA2DA958533C8026E58739211E569770E3707B2689D6E631B4F27B7E7BD662`
- Pre-refactor code observed: esa_arm.py `5DDD1779...`, esa_core.py `7206F958...` (identical), esa_property_tests.py `4116C440...`; all 60 unit checkpoints record these.

## Verdict

**APPROVE_FOR_FREEZE_WITH_REQUIRED_CHANGES.** Findings: P0 0, P1 0, P2 2, P3 3; one blocking (D-01, a one-line code fix). Apply D-01 (and preferably D-02) before the freeze, then freeze and launch.

## Path-only refactor: PATH_ONLY

My own unified diff of `code_prerefactor_20260926/` against `src/` is line-for-line the editor's `PATH_REFACTOR_20260926.diff`. esa_core.py is byte-identical. esa_arm.py changes 13 lines: a `RAW_ROOT` constant read from `ESA_ADB_RAW_ROOT` with the unchanged default, `run_dir` derived from the file location with a fail-closed RuntimeError if the folder name is not `RUN_ID`, and the three Config path arguments. esa_property_tests.py changes 5 lines of the same kind. No constant, seed, chunk size, mask, model setting, metric or unit function is touched. `PATH_REFACTOR_CHECK.json` shows identical resolved configuration, an identical 147-unit plan (I recomputed the UNIT_PLAN.json hash) and byte-identical prep outputs for channels 12, 41 and 61; those nine hashes equal the PT2 hashes and the prep checkpoint hashes. The pre-freeze evidence therefore carries over to `src/`. The remaining provenance gap (two hash sets) is D-03.

## F1 closure

All sixteen findings are CLOSED.

| F1 | v3 field | Code | Note |
|---|---|---|---|
| 01 | assay_sensitivity, per_detector_test, decision_rule, decision_artifact | unit_decision 1178-1202 | Toy run reproduced statuses and the LR bound by hand |
| 02 | public_freeze.when (verbatim), stop rules 6-7, PT1 quarantine | assert_frozen at the top of unit_fit; --stop-before-fit; run_status COMPLETED at 60/147 | Gate binds code hashes |
| 03 | staleness, PT2, staleness_diagnostics, stale_peak_exclusion | window_ages (brute-force verified), stdz max over channels, eval shares and variants | Primary and H-E1 unchanged |
| 04 | S_L redefined, 62-of-65 sentence | eval skips E3 for light; AUROC only for 0<m<6 | |
| 05 | test_subperiods, drift_split, E4_period_and_year_context | DRIFT_START_NS, sub_rows, year_rows, remapped variants | Deviation (start-time assignment, separate queues) justified |
| 06 | E4 chance recall, E4_vor_corrected_event_wise | chance_recall, vor_corrected_event_wise | Time-domain reading justified; point-event defect D-01 |
| 07 | models.settings.pca | svd_solver covariance_eigh, solver recorded | |
| 08 | test_label_lock | | Verbatim opening with F3 hash |
| 09 | aggregated_masses_secondary, E2 | EpisodeAggregator, combine_replicate_aggregates identical to the synthetic aggregation on toy data | |
| 10 | float32/float64, chunking, model_call_cap, durability, Section 10 file | episode_subsample matches the seed rule; all 31 Section 10 fields present; TIMEOUTS from measured units, margin 3 | TreeSHAP cap extension justified |
| 11 | manuscript_boundary, Q-E1 | | |
| 12 | standardization guard, PT3 | guarded, unit_stdz; PT3 lists no guarded column | Raw-deviation extension justified |
| 13 | PT1 all six families | PT1_RESULT: 6 families, 266 artifacts, pass | Also certifies run-to-run determinism |
| 14 | percentile primary, Student-t, class cluster | t_lower_bound, cluster_bootstrap_lb verified | |
| 15 | 0.477/0.508, no test gaps, 10 pairs | eval reports overlap pairs and multi-event episodes | |
| 16 | model_index, window_period_rule, paired shuffle, quantile linear | 3 straddling windows per boundary (6 total = stats.json) | Boundary deviation justified |

## Label isolation, freeze integrity, PT1

Labels are read at exactly one site, `read_segments`. `unit_stdz` calls it with `pre_evaluation=True` (rows with StartTime < 2007-01-01, EndTime clipped); `unit_eval` calls it with `pre_evaluation=False` and is the first reader of test rows. prep reads no label; fit, episodes and attr_episode read only stdz outputs. No pre-evaluation artifact can depend on a test-period label row: the filter removes them, and the period masks confine nominal, supervised and raw statistics to fit and validation windows. PT1 as run edits only the 1,711 test rows, covers all six families with episodes and attribution artifacts (266 files, hashes only, quarantined), and passed; it detects any read of test rows before the filter and cannot be fooled by a second reader because none exists. Its pass is meaningful.

The freeze gate sits in `unit_fit`, the only function that scores windows; every later unit needs fit outputs. Nothing before the freeze exposed a test-period score, flag, threshold or episode count: status, logs, heartbeat and stats carry counts and geometry only; PT1_RESULT carries hashes; by construction `Runner.log_unit` never prints the checkpoint `extra` fields, so the PT1 transcript read for durations holds none of the smoke's thresholds or flag rates.

## Findings

**D-01 (P2, blocking) - `esa_core.clip_intervals` drops zero-length event segments.** `keep = e2 > s2` removes point segments from the merged event union that decides FPe in `vor_corrected_event_wise`. An alarm overlapping only a point event is then a true positive for the event and a false positive at once, against the protocol's own definition of FPe. The test labels hold 108 zero-length rows, three zero-duration test events (id_118, id_42, id_55) and 26 zero-length rows in five events (id_118, id_183, id_186, id_187, id_189) that no positive-length test segment covers. Toy test: alarms [150,250], [300,350], [690,710], [900,950] s against events [100,200], [400,450] (rare) and a point at 700 s gave TPe 2, FNe 1, FPe 3, Pre 0.32; with the fix FPe 2, Pre 0.40. Required change: replace `keep = e2 > s2` with `keep = e2 >= s2` in `clip_intervals`. Alarm spans are never zero-length, so FPt and Nt are unchanged.

**D-02 (P2, not blocking) - eval memory.** `unit_eval` accumulates the episode rows of all six models as 27-key dicts before building one DataFrame. Measured: 300,000 rows take 620 MB, 808 MB at the conversion peak. With the 20,000-episode cap expected to bind, six models can reach 120,000-300,000 rows and exceed the 700 MB floor on a host with 1.5-2 GB available; eval has no freeze gate, so a post-freeze patch would run under a code hash that differs from the freeze record. Required change: build `pd.DataFrame(model_rows)` at the end of each model iteration, append to a list, and `pd.concat` at write time. Output bytes unchanged. Apply before the freeze.

**D-03 (P3) - code lineage.** The 60 pre-freeze checkpoints and PT1-PT3 carry the pre-refactor hashes while the frozen code carries the post-refactor hashes, and the raw root now depends on `ESA_ADB_RAW_ROOT`. Required change: add to execution.code_snapshot the sentence naming both hash sets, the diff and check files, and that `ESA_ADB_RAW_ROOT` is unset or equal to `C:/ESA_ADB_RAW` at launch (exact text in DELTA_REVIEW.json); include the diff and check files in the freeze package.

**D-04 (P3) - S_L window AUROC negatives.** In the six-channel refit, windows of the 26 test events that touch no lightweight channel are non-scoreable and count as negatives in window AUROC/AP, while the false-alarm rule excludes them from nominal time. Primary set unaffected (every test event is scoreable). Required change: one sentence in endpoints.E4 stating positives, negatives and the S_L inclusion. No code change.

**D-05 (P3) - wording.** public_freeze.when calls PT2 and PT3 part of "the PT1-PT3 smoke on the bounded subset", but PT2 runs three channels on the full grid and PT3 on the full standardization outputs; the PT1 text omits the smoke's N_fit = 20,000 and N_bg = 5,000. Exact replacements in DELTA_REVIEW.json.

## Checks performed

Hashes of protocol, code, pre-refactor code, plan, F3 facts and PT results; own diff of the refactor; full read of the three frozen files plus verify_path_refactor.py and verify_f1_facts.py against v3, common.py, models.py, run_criticality_unit.py, criticality_analysis_v4.py, prepare_inputs.py and the VOR text; 43 toy tests in a scratch directory (features identical to common.window_features after the float32 cast, chunk independence, tail surprisal, mass normalization and episode aggregation identical to the synthetic core including degeneracy, raw and feature masses identical to prepare_inputs, ranking AUROC equal to sklearn with ties, Hit@k chance against Monte Carlo, bootstrap and Student-t and class-cluster bounds against the protocol text, MUC-AUC equal to the synthetic curve with identical tie orderings, VOR toy including the anomalies-only exclusion, window periods on the real grid, brute-force segment and grid masks, zero-order hold and ages, episode runs across invalid windows, occlusion and native attributions bit-identical to models.py for lr, pca and hgb and batching-invariant, cap subsample, e3 and e2 smoke, decision unit on a synthetic E1 table, guard rule, event remapping); label-table recounts; Section 10 fields; controlled-stop evidence; resource estimates (fit 186 MB plus model, scoring 93 MB chunks, E3 about 22,000 small assignments); manuscript claim boundary; owner conformance.

## Checks not run

PT1 smoke outputs, its CLI log and the work folders (quarantine); no fit or score on real data (AE fit not executed, code byte-identical to models.py); supervisor script and other src/ scaffolding (outside the whitelist); the official ESA-ADB metric code (no network); license re-observation and archive integrity (taken as recorded); eval wall clock (analytic estimate only).

## Summary

v3 implements all sixteen F1 changes and the five declared deviations are justified. The code matches v3 and the synthetic core in every decision-critical definition I could test, label isolation holds with a single filtered reader, the freeze gate blocks every scoring path, and the pre-freeze evidence carries over to the path-only refactored src/. One blocking defect: vor_corrected_event_wise drops zero-length event segments, so alarms on point events count as false positives (one-line fix). One memory risk in the eval unit and three wording or provenance notes. Freeze after applying D-01.

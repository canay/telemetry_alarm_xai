# F1 independent protocol review: ESA-ADB Mission1 bounded arm (v2 candidate)

Date/time: 2026-09-26 14:24 +03:00
Tool: Claude Code (guarded CLI)
Model: claude-fable-5-1 (independent reviewer; not the editor)
Operation ID: f07-rb4-esa-adb-revision-20260926
Review ID: F07-ESA-ADB-F1-REVIEW

Candidate: `experiments/2026-09-26_claude_isyeri_notebook_esa_adb_mission1_arm/ESA_ADB_PROTOCOL_CANDIDATE_V2.json`
Candidate SHA-256: `7AC751A67F32CB1C79B4A33049D1A17EF9FF9570BC72EDA8BCDF24B99C9A7575`
F3 facts SHA-256 observed: `CEA577398906FE4BA3D23E2345B4D8D71CD4487A83ADFD4B706D73AB65287F16` (matches the protocol)

## Verdict

**APPROVE_WITH_REQUIRED_CHANGES.** Findings: P0 0, P1 3, P2 10, P3 3; five are blocking (F1-01 to F1-05).

The design is faithful to the synthetic core, every deviation I could trace is declared, test labels reach no pre-evaluation stage, and PT1-PT3 can catch a plumbing leak and can be satisfied by a correct deterministic pipeline. The blocking defects are about informativeness and freeze integrity, not about leakage: the decision rule can return SUPPORTED at chance, the freeze may follow test-period scoring, zero-order-hold staleness can manufacture the false-alarm structure Q-E2 measures, the lightweight E1 is empty, and the documented 2012-2013 drift has no prespecified split.

## Summary

The v2 candidate is faithful to the synthetic core, declares its deviations, keeps test labels out of every pre-evaluation stage, and its property tests can catch a plumbing leak. It cannot be frozen as written for five reasons: the non-inferiority rule has no assay-sensitivity gate and can return SUPPORTED at chance, since long events make detection near-automatic; the freeze may follow test-period scoring, so flag rates could be seen before rules lock; zero-order-hold staleness during unlabeled gaps can manufacture the false-alarm concentration Q-E2 measures; the lightweight E1 is empty (62 of 65 events affect all six channels); and the documented 2012-2013 drift needs a prespecified period split. Eleven further P2/P3 items are wording, fidelity or feasibility fixes.

## Findings

### F1-01 (P1, blocking) — H-E1 can be SUPPORTED when neither mass carries information
Section: `hypothesis_H_E1.per_detector_test`, `decision_rule`.
Issue: The pass rule LB > -0.06 has no assay-sensitivity condition. Detection is close to automatic for long events: 30 of the 91 test events last at least 24 h and 17 last at least 7 days, so under a label-independent Bernoulli flag model at the 1 percent nominal flag rate implied by the 0.99 threshold about 59 of 91 events are detected by chance (40 with probability above 0.95). Their peak windows are maxima over thousands of near-nominal windows. If native and feature AUROC both sit near 0.5 with small variance, D is near 0, LB exceeds -0.06, and four of five detectors pass while the arm has learned nothing.
Evidence: protocol fields named above; `event_schema_table.csv` durations recounted (median 6.1 h, 75th percentile 77.7 h); `models.threshold`.
Required change: Amend per_detector_test to: "A detector is evaluable iff n >= 30 detected scoreable events with 0 < m < C AND its native mass passes assay sensitivity: the one-sided 95 percent lower bound of the native mean AUROC (5th percentile of 2,000 event-resampled means, numpy default_rng(20260926 + 100 + model_index)) exceeds 0.5. A detector that fails assay sensitivity is reported NOT_INFORMATIVE and does not count toward k. Among evaluable detectors, pass iff LB > -delta." Persist the assay statistic, bound and flag in the decision artifact.

### F1-02 (P1, blocking) — Freeze timing permits test-period scores to be seen before the rules lock
Section: `public_freeze.when`, `stop_rules_and_hard_stops` item 6, `execution.atomic_units`.
Issue: The freeze is required only before the evaluation stage opens test labels, and the change prohibition is keyed to that same event. The fit units write validation and test scores and the episodes units write thresholds, flags and episode counts before it. Flag rates and episode counts are outcome-informative without labels, so thresholds, masses, margin or rule could be changed after seeing them while honoring the letter of the lock.
Evidence: the three protocol fields; v1 Section 0, which required the freeze before any test label is opened and which v2 weakens in practice.
Required change: public_freeze.when = "After the independent review and the editor's decision, before any fit:<set>:<model>:<rep> unit on the full data and before any test-period window is scored. Only prep:<channel>, stdz:<set> and the PT1-PT3 smoke on the bounded 2006-07-01..2007-06-30 subset may precede the freeze; the smoke's scores, thresholds, flag rates and episode counts are quarantined (hash-recorded in the freeze package, not inspected)." Stop rule 6 becomes "after the public freeze, no change to ..." and a new stop rule reads "no test-period score, flag, threshold, episode count or flag rate is inspected before the freeze".

### F1-03 (P1, blocking) — Zero-order-hold staleness during unlabeled gaps can manufacture Q-E2's result
Section: `preprocessing_label_free.resampling`, `windows`, `endpoints.E2/E3/E4`.
Issue: ZOH turns every unlabeled data gap into windows of constant values (sd, slope, delta exactly zero across many channels at once) that are "valid" under the finiteness rule. Gaps are frequent and long: 30 s channels have 0.2-0.5 percent of intervals above 30 s with maxima near 5.9 h, channels 64-66 reach 28 h, channels 70-76 reach 13 days, channels 61-63 reach 23 days. All four labeled communication gaps lie in the fit period, so every test-period gap is unlabeled and any episode it triggers is a false alarm attributed to whichever channel's frozen features are most unusual. VOR Appendix B.2 records that sampling-rate gaps are detected as anomalies by many algorithms. E2 concentration and E3 spike correlations could therefore be artifacts of the arm's own preprocessing; no staleness diagnostic exists.
Evidence: `channel_sampling.csv` (max_interval_s, share_intervals_gt_30s); `F3_FACTS.json` (4 gaps, all fit); VOR B.2 and C.3.
Required change: Add a label-free per-window staleness feature in prep:<channel>: age_c = window end minus the timestamp of the last original sample at or before the window end; staleness = max over analysed channels; store beside the features and cover in PT2. Fixed rule: stale iff staleness > 3,600 s (four times the slowest 900 s cadence). Prespecify: (i) share of stale windows per period and, per detector, the share of flagged windows, episodes, false-alarm episodes and detected-event peaks that are stale; (ii) E2, E3 and E4 recomputed excluding episodes whose peak window is stale, as a prespecified sensitivity; (iii) primary definitions and H-E1 unchanged.

### F1-04 (P2, blocking) — The lightweight E1 cannot be executed
Section: `secondary_prespecified_descriptive.S_L_lightweight`, `data.channel_sets.secondary_lightweight`.
Issue: Of the 65 test events touching channels 41-46, 62 affect all six (m = C: AUROC undefined, Hit@k trivially 1); only id_157 (m = 5), id_42 (m = 1) and id_55 (m = 3) have 0 < m < 6.
Evidence: recount of `meta_labels.csv` against channels 41-46; `F3_FACTS.json` test_lightweight_scoreable_events = 65.
Required change: Delete S_L's E1, or redefine S_L as descriptive detection context on the six-channel refit (E4 quantities and E2 false-alarm concentration, false-alarm rule still using labeled segments on any channel) and state: "62 of 65 lightweight test events affect all six channels; channel-ranking metrics are reported only for the 3 events with 0 < m < 6 and carry no inference."

### F1-05 (P2, blocking) — The documented 2012-2013 drift needs a prespecified period split
Section: endpoints E1-E4.
Issue: Seven test years are scored against a threshold from three months of 2006. VOR Table 6 documents severe concept drift in channel groups 4, 7 and 13 during the last 18 months (from about 2012-07-01); 21 of 91 test events start in that window, and 21 of the 23 three-channel test anomalies affect channels 14, 21 and 29, which are group 4. A fixed threshold can flag the drift era almost continuously (giant true-alarm episodes, the V5 pattern) and shift the false-alarm set to the pre-drift years. With exploratory authorization "none", a period split cannot be added later.
Evidence: VOR Table 6; `meta_channels.csv` groups; `event_schema_table.csv` (2012: 10 events, 2013: 14); recount of the three-channel events.
Required change: Prespecify descriptive stratification of E1 (per-event AUROC means and counts), E2, E3 and E4 by [2007-01-01, 2012-07-01) versus [2012-07-01, grid_end], boundary fixed now from VOR Table 6. Add per calendar year and per detector: flag rate, episode count, episode-length distribution (windows per episode, maximum) and the number of episodes overlapping more than one event. The pooled H-E1 decision is unchanged.

### F1-06 (P2) — Detection context lacks the chance-detection reference and the official metric
Section: `endpoints.E4`.
Issue: Raw event recall is not interpretable when most long events are detected by chance, and no chance reference is planned. The VOR's primary metric (corrected event-wise precision, recall and F0.5, Eq. 1-2) is what readers will compare against; its Table 4 shows event-wise precision below 0.001 for every unsupervised detector on the full Mission1 set.
Required change: Add per detector: (i) expected event recall under a label-independent Bernoulli flag model at the realized nominal flag rate, computed at evaluation from each event's overlapping-window count; (ii) corrected event-wise precision, recall and F0.5 (VOR Eq. 1-2) in the time domain from the arm's episodes, for anomalies plus rare events and for anomalies only, descriptive, with the note that the arm's detectors are not ESA-ADB competitors.

### F1-07 (P2) — The PCA solver rationale is false
Section: `models.settings.pca`.
Issue: "svd_solver='full' is the solver the synthetic core resolved to by default" is wrong. In scikit-learn 1.5 and later (fresh replication 1.7.2, planned 1.9.0) 'auto' resolves to 'covariance_eigh' whenever n_features <= 1000 and n_samples >= 10 x n_features, which holds for the synthetic core (2,277 x 48) and the ESA fit (100,000 x 232); before 1.5 the same shapes resolved to 'randomized'. Numerically minor for 10 components, but a frozen protocol must not carry a false fidelity statement.
Evidence: installed scikit-learn 1.9.0 `sklearn/decomposition/_pca.py` PCA._fit auto branch; manuscript Appendix (1.7.2); `models.py` line 67.
Required change: Set svd_solver='covariance_eigh' or keep 'auto' and record the resolved solver in the run manifest; state that 'full', 'covariance_eigh' and the legacy 'randomized' default differ only numerically here and that random_state is inert for exact solvers.

### F1-08 (P2) — The test-label lock statement contradicts the F3 read
Section: `label_usage.test_label_lock`, `endpoints.E1_reason_for_metric_change`.
Issue: F3 already read every test-period label row (counts, affected-set sizes, per-event start and end), and that information changed the primary metric, the m = C exclusion and S_L. Acceptable label-structure use, but the lock must say exactly what was read and what it changed.
Required change: Begin test_label_lock with: "Test-period label rows were read once before the freeze by the hash-bound F3 schema inspection (F3_FACTS.json sha256 CEA577...) for category counts, affected-set sizes, split membership and event time ranges only; no preprocessing artifact, score or detector existed at that time. The facts changed the primary metric (Hit@3 to AUROC), the m = C exclusion, the S_L scope and the n >= 30 feasibility judgment, and nothing else."

### F1-09 (P2) — Peak-window episode masses are not comparable with tab:mechanism
Section: `channel_masses.query_windows`, `endpoints.E2`.
Issue: E2 concentration is computed on episode-peak masses, whereas tab:mechanism and the matched-information policy inputs used tau-weighted aggregates over all flagged windows (`prepare_inputs.py` lines 72-77; `run_criticality_unit._aggregate_episode_attributions`). Peak masses are sharper, so E2 entropies cannot be compared with the manuscript's 0.096-0.947. The cost argument holds only for occlusion and TreeSHAP; raw and feature masses over all flagged windows need no model call and native LR/PCA/AE masses are closed form.
Required change: Add a prespecified secondary with the synthetic tau-weighted aggregation for raw deviation, feature deviation and native LR/PCA/AE over all flagged windows; occlusion and TreeSHAP natives stay peak-only; report peak and aggregated concentration separately and compare only the aggregated values with tab:mechanism.

### F1-10 (P2; blocking for launch, not for freeze) — Resource and durability plan is unmeasured and incomplete
Section: `execution`.
Issue: Full-grid features are about 2.9 million windows x 232 features (2.7 GB float32, 5.5 GB float64) against about 1.1 GB available RAM, with no dtype, memmap or chunked-scoring rule; PT1 byte identity needs deterministic chunking. Episode occlusion cost is unbounded (n_episodes x 58 x 8 scored rows per replicate); at a 20 percent drift-era flag rate isolation-forest scoring alone exceeds the 90-minute unit timeout. Owner Section 10 fields missing: eta_basis_and_margin (no measured unit time), opaque_runtime_bound_admission, code_snapshot_path_and_sha256, local_delivery_and_verification_rule, stall threshold, terminal_status_paths, resume_validation_rule detail, aggregate/plot entrypoints, max_workers; heartbeat lacks run_id, attempt_id, pid, completed/planned units and last checkpoint time.
Required change: Before launch the experiment plan or RUN_MANIFEST carries every Section 10 field; features float32 on disk with float64 accumulation and a fixed chunk size; a prespecified occlusion cap (more than 20,000 episodes: fixed-seed subsample of 20,000, numpy default_rng(20260926 + model_index), all other masses on every episode); per-unit timeout and watchdog from measured smoke unit times with a stated margin; a measured available-RAM baseline before the run.

### F1-11 (P2) — The margin equals the synthetic worst case; the claim must carry the number
Section: `hypothesis_H_E1.margin`, `manuscript_boundary`.
Issue: delta = 0.06 is the rounded-up largest synthetic native advantage (recomputed: HGB 0.0545, PCA 0.019, AE 0.013, LR 0.008). Prespecified and transparent, but SUPPORTED is then compatible with native beating feature mass by as much as the synthetic worst case.
Required change: Add to manuscript_boundary: "A SUPPORTED H-E1 is reported as 'feature-deviation mass ranks the annotated affected channels within 0.06 AUROC of native explanations (non-inferiority margin fixed before any fit)', never as 'as well as'; D and LB are reported beside the verdict."

### F1-12 (P2) — No guard for zero-variance nominal feature columns
Section: `models.standardization`, PT3.
Issue: z = (f - mean)/(sd + 1e-9) assumes no nominal column is constant. Real telemetry can hold a channel constant for the whole fit period, giving z of order 1e9 that dominates PCA and AE reconstruction error and every mass. PT3 checks finiteness only.
Required change: Extend PT3 with "every raw feature column has nominal-fit standard deviation > 1e-8 x max(1, |mean|)"; prespecify that a failing column is frozen at z = 0, recorded in the run manifest, and its channel's masses flagged in the per-event and per-episode tables.

### F1-13 (P2) — PT1 covers two of six families
Section: PT1.
Issue: Only LR and PCA are exercised, so a family-specific label-dependent path in HGB, decision tree, isolation forest, autoencoder or the TreeSHAP attr_episode units would pass PT1. The one-year subset makes all six cheap.
Required change: Run PT1 with all six families at one replicate on the bounded subset, including each family's episodes and episode-mass artifacts, and require byte identity for all.

### F1-14 (P3) — Bootstrap method and event clustering
Section: `hypothesis_H_E1.per_detector_test`.
Issue: The 5th-percentile bootstrap is the method V4 replaced with a Student-t bound; at n >= 30 the gap is small but paired AUROC differences are bounded and skewable. Events of one class are near-replicates (21 class_7 anomalies on channels 14, 21, 29).
Required change: Report both the percentile LB and the one-sided 95 percent Student-t LB and name the primary; add a descriptive cluster bootstrap over anomaly_types Class.

### F1-15 (P3) — Factual slips
Section: `E1_reason_for_metric_change`, `communication_gaps`, `E4`.
Issue: Mean chance Hit@3 over the 89 evaluable events is 0.477 (0.508 at the median m = 12), not "near 0.6"; all four gap labels are in the fit period, so the test gap-overlap count is 0 by construction; 10 pairs of test events overlap in time (id_55 inside id_155, id_145 with id_146, id_180 with id_181, and others).
Required change: Correct the chance value; state that the test period carries no gap labels; add the overlapping-pair count to E4 and state that an episode overlapping two events is matched to at most one.

### F1-16 (P3) — Definitional gaps
Section: `models.replicates`, `endpoints.E3`, `label_usage.nominal_windows`, PT1.
Issue: model_index is undefined; a window straddling 2006-10-01 or 2007-01-01 has no period; PT1 (c) does not say that (StartTime, EndTime) are shuffled as paired values, and byte identity would fail if any artifact records the label-table hash; the quantile method is unnamed.
Required change: model_index = position in models.families; a window belongs to the period containing its start time; PT1 (c) shuffles (StartTime, EndTime) pairs and channels as whole values over a named artifact list that excludes provenance fields; threshold uses numpy.quantile default linear.

## What was checked and agreed

- Windows (W = 20, stride 5), features and layout, standardization, LR/DT/HGB/IF/PCA/AE settings, replicate and bootstrap seeds, occlusion seeds and once-per-call draw sharing, mass normalization and replicate averaging, tail surprisal, one-to-one matching and MUC-AUC all match `common.py`, `models.py`, `run_criticality_unit.py`, `criticality_analysis_v4.py`, `prepare_inputs.py` and the manuscript equations. The HGB early-stopping deviation is correct (synthetic labeled sets had 4,937 windows, below the 10,000 auto threshold). The N_fit cap and 50,000-window background are declared and harmless.
- Leakage: no pre-evaluation stage can read a test-period label; PT1 (b)/(c) would change the evaluation-only inputs and must leave every pre-evaluation artifact identical, which a deterministic pipeline can satisfy; PT2 and PT3 are sound.
- F3 facts recomputed exactly from the CSVs; archive hashes consistent; no event or segment spans a split boundary.
- Per-event AUROC is the right primary given affected sets of 1-58 channels (median 12), chance 0.5 for every m; secondary chance formulas are correct; ceil(0.8 k) is consistent with v1 at k = 5.
- post_gate_continuation and evaluator_semantics blocks conform to the schema-v3 owner; non-claims and the manuscript boundary are honest, and the arm addresses the "no real-telemetry support" objection for channel evidence and false-alarm load while correctly leaving the criticality-weighted decision-utility contrasts synthetic-only.

## Checks performed

1. SHA-256 of the candidate (7AC751A6...) and of F3_FACTS.json (CEA57739..., matches); archive size, MD5 and SHA-256 consistent.
2. Recount of all F3 facts from the three metadata CSVs (3,589 rows, 200 events, split counts, 91/2/89 test events, affected-set distribution).
3. Lightweight-subset evaluability (65/62/3).
4. Channel composition of the three-channel test events versus VOR Table 6 drift groups.
5. Test-event durations, overlapping-window counts and Bernoulli chance detection at 0.5, 1, 5 and 20 percent flag rates.
6. Events per year, events from 2012-07-01, labeled-time fraction per period, window counts per period.
7. Overlapping test-event pairs and point events.
8. Chance levels (Hit@1 0.259, Hit@3 0.477, R-precision 0.259) and margin recomputation.
9. Line-by-line fidelity against the five code files and the manuscript.
10. scikit-learn 1.9.0 PCA auto-solver policy from the installed source.
11. Leakage walk-through of every pre-evaluation stage and of PT1-PT3.
12. Cadence and gap facts from channel_sampling.csv.
13. Owner-document conformance (design, durability Section 10, evidence requirements schema v3).
14. Manuscript claim-boundary check.

## Checks not run

- Zenodo license re-observation (no network); taken as recorded.
- Raw archive inspection (constant channels, gap locations, drift magnitude): forbidden by the packet.
- HGB/TreeSHAP determinism under OMP threads = 2 for PT1 byte identity: no fit allowed; flagged for the smoke.
- scikit-learn 1.7.2 behavior inferred from the 1.9.0 source and the 1.5 release note; 1.7.2 not installed.
- Official ESA-ADB metric code not read (network forbidden); recommendation follows VOR Eq. 1-2.
- VOR Appendix D is absent from the provided text extract.

2026-09-26 14:24 +03:00; Claude Code; claude-fable-5-1; f07-rb4-esa-adb-revision-20260926

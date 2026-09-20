# When explanations help alarm review: Scenario-conditioned utility in spacecraft telemetry

Curated replication and public-freeze package for the study “When explanations help alarm review: Scenario-conditioned utility in spacecraft telemetry.”

This repository separates anomaly detection, fault-channel salience, explanation stability, and operational alarm-review utility over aligned episodes. Release `v1.1.0` froze, before any confirmatory generation, the exact V4 scenario-heterogeneity protocol, code, seed range, five-condition decision rule, null calibrations, joint-power calculation, and provenance driver. The bundled V3 outputs are explicitly exploratory; they are not confirmatory evidence.

Release `v1.2.0` publishes the outcome without changing that freeze. The seeds 10--29 replication stopped before policy or null endpoint analysis because seed 12 isolation forest produced 9 alarm episodes against the preregistered minimum of 10. The property suite passed 1,248 of 1,249 checks, the run closed as `NOT_CONFIRMED_PROPERTY_GATE`, and no threshold reduction, replacement seed, model exclusion, or other rescue was performed. The result therefore reports an analyzability failure, not a zero effect and not a successful replication.

Release `v2.0.0` prospectively freezes a distinct V5 confirmation that repairs
the general analyzability defect by using seven independently generated test
trajectories per seed and a pooled-queue gate of 20 episodes. The endpoint-blind
R=7 pilot passed 397/397 checks, discovery-only planning retained the protocol
floor of 20 seeds after both fixed-mean power and predictive assurance reached
0.80 at seven seeds, and confirmation is restricted to untouched seeds
300--319. This release contains the plan, pilot summary, code, and hashes; it
does not contain the V5 confirmation outcome.

Release `v2.1.0` publishes that outcome without altering the freeze. The
confirmation stopped before any policy, null, construct, or endpoint analysis:
two of 3,089 property checks failed when one persistent seed-303 alarm episode
spanned three non-overlapping injected events in both PCA and autoencoder
outputs. Because the frozen matcher already supports multi-event episodes, the
failure is classified as `FIXED_GATE_MISSPECIFIED`; nevertheless the public
protocol makes it terminal. V5 therefore closes as
`NOT_CONFIRMED_PROPERTY_GATE`, with no endpoint and no rescue.

Release `v2.2.0` is a provenance-only transfer-artifact correction. It carries
the already frozen 2026-07-28 OPSSAT-AD and KDDCup99 signature repairs into the
public `results/` tree: isolation-forest signatures use raw anomaly-score
perturbations, and zero-norm signature pairs are explicitly excluded. Detection
predictions, V4/V5 protocols, V4/V5 property outcomes, manuscript estimates,
and the no-endpoint/no-rescue conclusions are unchanged. Each corrected transfer
directory contains a hash-bound `signature_repair_provenance.json` record.

Release `v2.2.1` is a release-hygiene patch. It normalizes the six corrected
transfer CSVs to LF and regenerates both provenance records from those exact
released bytes, so `signature_repair_provenance.json` and `checksums.sha256`
agree in fresh clones. Scientific values, predictions, protocols, property-gate
outcomes, manuscript estimates, and the no-endpoint/no-rescue conclusions are
unchanged.

The package also contains bounded transfer checks on OpenML 40900, KDDCup99, and OPSSAT-AD. These datasets support detection or within-model feature-signature repeatability only; they do not establish spacecraft fault-channel attribution correctness or operational deployment validity.

Release `f07-fresh-mta-results-20260920` adds the completed, prospectively frozen 40-seed MTA internal replication. The exact 20 sources and result tables are in [results/f07-fresh-mta-20260920](results/f07-fresh-mta-20260920/README.md); four downloadable release assets contain all 4,920 planned scientific outputs and 400 atomic checkpoint records, including generated synthetic data and fitted-model artifacts. The independent unit is the seed (n=40), and the four primary intervals use Bonferroni adjustment. See the package for the full directional decision, mandatory sensitivity results, scope limits, and registry timing disclosure. Earlier V4/V5 gate stops remain unchanged.

## Contents

- `code/`: synthetic telemetry generation, resumable detector work units, aggregation, statistical analyses, transfer checks, and figure scripts.
- `results/`: frozen JSON/CSV outputs used by the study, including primary synthetic results, ten-seed sensitivity analyses, KDDCup99 audit-rerun results, and OPSSAT-AD results with hash-bound signature-repair provenance.
- `data/README.md`: dataset acquisition and redistribution boundaries. Third-party raw datasets are not bundled; generated synthetic data for the new MTA replication are supplied as release assets.
- `REPRODUCE.md`: environment setup and reproduction commands.
- `ARTIFACTS.md`: claim-to-artifact map and scope limitations.
- `PROTOCOL_V1_1.md`: human-readable public-frozen confirmation protocol.
- `CONFIRMATORY_PLAN.json`: machine-readable required files, hashes, seeds, models, endpoints, and decision method.
- `POWER_PLAN_V4.json`: deterministic joint-power design artifact.
- `code/run_confirmation_v4.py`: remote-tag-bound driver that refuses pre-release or unregistered artifacts.
- `PROTOCOL_V2_0.md`, `CONFIRMATORY_PLAN_V5.json`, `POWER_PLAN_V5.json`, and
  `PILOT_PROPERTY_V5.json`: public V5 freeze and planning evidence.
- `code/run_v5_development.py`: release-bound, resumable V5 confirmation
  launcher; `code/confirmatory_analysis_v5.py` owns its five-endpoint decision.
- `results/scenario_utility_v1_2/`: exploratory manuscript aggregates, model-level figure, and the preregistered replication property-gate closure.
- `results/scenario_utility_v2_1/`: complete V5 property result, hash-bound run
  manifest, and gate-misspecification closure.
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

For the V5 confirmation, only after public release `v2.0.0`, use a new empty
directory outside the repository:

```bash
python code/run_v5_development.py \
  --mode confirmation \
  --release-root . \
  --run-root ../criticality_confirmation_v5 \
  --seeds 300-319 \
  --max-workers 2 \
  --null-draws 200
```

The launcher refuses a dirty or release-mismatched checkout, pre-release or
unregistered artifacts, a different seed block, and a release body that does
not bind the exact V5 plan hash.

## Full reproduction

See `REPRODUCE.md`. The synthetic data are generated deterministically from fixed seeds. External datasets remain at their original sources and are downloaded or fetched by the documented steps.

## License

The original code and package documentation in this repository are released under the MIT License. Third-party datasets are not relicensed here and remain governed by their source records.

## Citation

See `CITATION.cff`.

## Release provenance

Updated: 2026-08-30 04:08 +03:00
Tool: Codex
Model: GPT-5.6
Operation ID: `f07-v5-round-d-final-corrections-20260830`

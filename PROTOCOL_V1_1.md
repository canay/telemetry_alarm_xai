# Scenario-Heterogeneity Confirmatory Protocol V1.1

Date/time: 2026-08-26 17:52 +03:00  
Tool: Codex  
Model, if known: GPT-5  
Operation ID: `f07-criticality-v4-pre-freeze-repair-20260826`

Status: `DRAFT_REPAIRED_PENDING_FINAL_ADVERSARIAL_REVIEW_AND_PUBLIC_FREEZE`

## Discovery disclosure

Seeds 0--9 repaired the generator, calibrated property/null gates and exposed
the scenario-dependent direction. They are exploratory only. The original
universal-uplift omnibus failed (mean `-0.01087`; one-sided lower bound
`-0.01844`). Across the five pre-outcome tie-eligible models, the raw
occlusion-minus-score gain was `+0.03146` under platform survival and `-0.07671`
under payload-first.

The first V1.1 draft was blocked by an independent Opus review before release.
In particular, within-type utility permutation had different negative raw
offsets across scenarios (`-0.03873` and `-0.12091`). The final rule therefore
does not mislabel the raw payload loss as attribution-specific harm. It requires
both the operational score-baseline reversal and positive attribution
information relative to that within-type null in each scenario.

DTree is descriptive because its score tie-pair mass exceeded `0.50` in three
discovery seeds. The property artifact that recorded this gate predates policy
analysis (`property_tests.json`, 16:52; policy results, 17:15 on 2026-08-26).
The five-model set is primary, and the six-model result is a mandatory
sensitivity so the exclusion cannot hide a direction or decision conflict.

## Freeze and provenance boundary

Before any confirmatory data are generated, this protocol, the exact V4 code,
the joint-power artifact and `CONFIRMATORY_PLAN.json` must be committed, pushed
and published as GitHub release `v1.1.0` at
`https://github.com/canay/telemetry_alarm_xai`. The frozen driver must verify
the remote publication time, tag commit, clean checkout and code hashes. It
must abort if any seed 10--29 data file predates the public release or if a
stored data hash changes.

The remote tag is dereferenced independently through `git ls-remote` and the
GitHub API and must equal local `HEAD`. The release body publishes the SHA-256
of `CONFIRMATORY_PLAN.json`. The plan must enumerate the exact required code,
protocol and power-artifact set; a partial/self-selected hash list fails.
First start requires an absent or empty run root. Thereafter every data,
feature, model, cross-seed, analysis-checkpoint and metrics artifact is
registered by hash and release-relative time. Unregistered, pre-release,
partial or changed artifacts abort rather than silently resume.

## Untouched units and exact analysis

- Seeds: exactly `10--29` (`n=20`).
- Primary models: `lr`, `iforest`, `hgb`, `pca`, `ae`.
- Mandatory sensitivity: all six models, including `dtree`.
- Scenarios: the byte-frozen platform-survival and payload-first vectors.
- Amplitude scale: exactly `1.0`.
- Threshold: validation `q=.99`.
- Episode representation: all flagged windows, score-weighted attribution
  aggregation; peak-window attribution is not substituted.
- Matching: maximum-weight one-to-one alarm--event matching.
- Utility outcome: realized-load `MUC-AUC_0.40`.
- Exact score ties: 100 frozen random order draws.
- Within-type utility permutation: 200 frozen draws per
  seed--model--scenario; mean null gain is computed before seed-level testing.
- Uninformative-attribution calibration: permuted-context and noise-attribution
  rankings are each evaluated under both true and the same within-type-permuted
  utilities; their information-contrast false-gain rates are frozen gates.
- Decision: one-sample Student-t one-sided 95% lower bound across independent
  generator seeds. This replaces the draft's anticonservative percentile
  bootstrap at small `n`.

The full discovery covariance was inflated by the largest one-sided 95%
upper-SD multiplier and passed through the exact five-condition
intersection--union rule in 20,000 deterministic simulations per candidate
sample size. The public artifact recommends `n=17` for at least 80% joint
power; `n=20` is frozen as a buffer. Seed choice is independent of outcomes.

## Estimands

For seed `s`, model `m` and scenario `q`:

`D(s,m,q) = MUC-AUC_0.40(occlusion_context) - MUC-AUC_0.40(score_only)`.

Let `N(s,m,q)` be the mean gain under within-fault-type permutation of event
utility across the 200 frozen draws. Across the five primary models:

- `P_s = mean_m D(s,m,platform_survival)`;
- `L_s = mean_m D(s,m,payload_first)`;
- `H_s = P_s - L_s`;
- `I^P_s = mean_m [D(s,m,platform_survival)-N(s,m,platform_survival)]`;
- `I^L_s = mean_m [D(s,m,payload_first)-N(s,m,payload_first)]`.

`P`, `L` and `H` answer the operational comparison with score-only review.
`I^P` and `I^L` ask whether the real attribution carries utility information
beyond an exchangeable within-type channel--utility relationship. The null is
not silently treated as zero.

## Confirmatory rule

The claim succeeds only when all five frozen conditions pass:

1. one-sided 95% lower bound for `H_s` is `>0`;
2. lower bound for `P_s` is `>0`;
3. lower bound for `-L_s` is `>0`;
4. lower bound for `I^P_s` is `>0`;
5. lower bound for `I^L_s` is `>0`.

This is an intersection--union claim: every condition is necessary, so no
multiplicity correction is needed to control the conjunction at alpha .05.
No favourable model, scenario or endpoint subset can rescue failure.

## Integrity gates

- V4 generator/model property suite passes on exactly seeds 10--29.
- Tie-pair mass `<=0.50` is mechanically enforced for every primary-model
  seed; DTree remains descriptive.
- Positive false-gain rates for permuted-context, noise-attribution and
  within-type utility controls are `<=0.05`, separately by scenario. The
  information contrast itself is additionally calibrated with both
  uninformative-attribution families and must have false-gain rate `<=0.05`.
- `policy_summary.csv` contains exactly seeds 10--29 with no duplicated frozen
  cells; property metadata records the same generator and model seed sets.
- Analysis checkpoints bind to V4 code SHA-256, seed and 200-draw contract.
- Analysis checkpoints also bind to the immutable run contract. Every dataset
  stores and revalidates amplitude scale `1.0`.
- Remote tag commit, release-body plan hash, required code set, artifact hashes
  and release-relative timestamps pass before `CONFIRMED` can be written.

## Mandatory sensitivities and failure boundary

All six-model versions of the five endpoints are always reported. Any primary
versus six-model direction or PASS disagreement appears alongside the primary
result in the abstract and discussion. After primary confirmation, amplitude
scales `0.5` and `1.5` use seeds `100--105` as descriptive robustness only;
they cannot rescue or upgrade the confirmatory decision.

Any failed primary condition yields `NOT_CONFIRMED`. No new weight, metric,
scenario, model exclusion, seed range or endpoint is permitted. Passing supports
a controlled synthetic operational reversal with attribution information above
the frozen null in both scenarios. It does not establish real operator utility,
flight deployment, causal diagnosis or universal XAI benefit.

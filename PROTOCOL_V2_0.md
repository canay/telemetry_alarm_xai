# Prospective V5 replicate-pooled confirmation protocol

Date/time: 2026-08-30 01:21 +03:00
Tool: Codex + Claude CLI 2.1.240 / Opus 5
Model, if known: GPT-5; Claude Opus 5, max effort
Operation ID: `f07-v5-public-freeze-20260830`

## Separation from V4

This protocol defines a new estimand and a new prospective confirmation. It
does not reopen, rescue, or reinterpret V4. V4 remains
`NOT_CONFIRMED_PROPERTY_GATE`: one of 1,249 frozen property checks failed
because `seed12_iforest` produced 9 eligible alarm episodes against a minimum
of 10, and no V4 endpoint was computed.

V5 addresses that analyzability defect before seeing any V5 confirmatory
endpoint. It increases independently generated test exposure; it does not
lower the gate, remove a detector, replace a seed, change the alarm threshold,
or inspect V4 endpoints.

## Frozen data-generating design

- Inferential unit: one generator seed.
- Per seed: 60 training, 30 nominal-validation, and 130 labelled-development
  orbits.
- Test exposure: seven independently generated 130-orbit trajectories.
- RNG: `numpy.random.SeedSequence(seed).spawn(26)`. Children 0--7 preserve the
  V4 streams byte-for-byte. Test replicate `r` uses children
  `5+3r, 6+3r, 7+3r`; children 0--13 also reproduce the failed R=3 pilot.
- Each test replicate contains six events from each of six frozen fault types;
  the pooled seed-level queue therefore covers 252 events over 910 test
  orbits.
- Raw trajectories are never concatenated. Windowing, thresholding, and
  episode segmentation occur separately within each replicate. Only completed
  episode records are pooled.

## Frozen model and queue construction

- Models: logistic regression, isolation forest, histogram gradient boosting,
  PCA reconstruction, autoencoder, plus decision-tree sensitivity.
- Three fitted-model replicates are shared across all seven test trajectories.
- Alarm threshold: mean-model nominal-validation 0.99 quantile.
- Episode rank magnitude: shared nominal-validation ECDF tail surprisal.
- Event IDs are namespaced as `36 * replicate + local_event_id`; episode IDs
  use `seed:replicate:local_episode`. Cross-replicate matching is forbidden.
- Every seed/model cell must have at least 20 pooled alarm episodes. This is a
  different 910-orbit estimand and a stricter absolute gate than V4, although
  its exposure-normalized requirement is lower (`20/252` versus `10/36`).

## Endpoint-blind pilot and discovery-only planning

Seeds 200--209 are reserved for property-only pilots. The R=3 pilot failed in
one cell: `seed208_iforest` yielded 12 pooled episodes with replicate counts
`[4,3,5]`. R=5 and R=6 lacked prospective margin. R=7 was the smallest fixed
exposure satisfying both the pooled-rate and worst-single-trajectory
constraints. Its rerun had to reproduce all first-three replicate counts and
was terminal: failure would have ended the positive route.

Pilot reporting was restricted to generator structure, episode counts,
threshold identity, and runtime. Policy scores, utility capture, nulls, and
endpoints were forbidden. `PILOT_PROPERTY_V5.json` records the passed R=7
pilot.

After pilot passage, original discovery seeds 0--9 were regenerated with the
seven-replicate exposure. They were used only for power and assurance planning;
no V4 confirmation or V5 pilot seed enters the confirmation.

## Frozen endpoints and populations

The five co-primary directional conditions are:

1. platform-survival minus payload-first raw gain is positive;
2. platform-survival raw occlusion-context gain is positive;
3. negative payload-first raw gain is positive, indicating avoided harm;
4. platform-survival information gain over its fault-type utility null is
   positive;
5. payload-first information gain over its fault-type utility null is
   positive.

For every condition, the one-sided 95% Student-t lower confidence bound across
seeds must exceed zero. All five must pass. The primary population is the
five-detector episode-weighted pooled queue. Mandatory sensitivities are the
six-detector episode-weighted pool and the five-detector trajectory-weighted
mean. Sensitivities can reveal disagreement but cannot upgrade a failed
primary result.

The pooled queue gives each completed episode one position and is therefore
episode weighted. The trajectory-weighted sensitivity gives each of the seven
test trajectories one seventh of a seed-level mean. Utility permutation is
restricted independently within the 42 `(replicate, fault type)` strata per
seed. Maximum-weight one-to-one matching, review fractions
0.05/0.10/0.20/0.40, maximum load 0.40, and frozen tie handling are unchanged.

## Power implementation clarification

The governing power calculation simulates the four base variables
`(platform raw, payload harm, platform information, payload information)` and
derives the scenario contrast as `platform raw + payload harm`. It applies the
same five-intersection Student-t rule used for confirmation. A same-sign mean
of the two raw scenario gains is a legacy universal-uplift diagnostic and is
not a frozen endpoint because the hypothesis predicts opposite signs.

`POWER_PLAN_V5.json` reports both a fixed-discovery-mean curve and predictive
assurance. The latter draws the latent four-endpoint mean from a normal
distribution centered on the discovery estimate with covariance
`Sigma/10`, then simulates the future confirmation with a conservative
chi-square-inflated covariance. The search begins at three seeds. The planned
sample size is the maximum of the fixed-mean recommendation, predictive-
assurance recommendation, and the pre-existing protocol floor of 20 seeds.
Both calculations recommend seven, so the frozen confirmation remains 20
untouched seeds, 300--319.

## Public freeze and untouched confirmation

- Public release tag: `v2.0.0`.
- Machine-readable owner: `CONFIRMATORY_PLAN_V5.json`.
- Confirmation may start only after the remote GitHub release timestamp.
- The driver verifies the public tag/commit, release-body plan hash, clean
  checkout, all frozen-file SHA-256 values, exact seed block 300--319, and
  post-release modification times plus registered hashes for every reusable
  run artifact.

## Kill switches and interpretation

If the property gate or any construct/null gate fails, no endpoint decision is
made. If any primary endpoint fails, the result is `NOT_CONFIRMED`. There is no
R=8/V6, seed replacement, detector removal, threshold relaxation, added
replicate, expanded seed count, or post-result rescue.

V5 tests a scenario-defined synthetic decision benchmark. It cannot establish
operator utility, causal diagnosis, flight-deployment benefit, or universal
superiority of an explanation method.

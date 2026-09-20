# Fresh MTA internal replication

Completed internal replication: **ALL_FOUR_EXPECTED_DIRECTIONS_SUPPORTED_WITHIN_PROTOCOL**.

Forty new seeds (1000–1039) were evaluated under the prospectively published MTA runtime amendment. All 400 atomic units completed. The 51,840 policy/profile/target cells are repeated measures; the independent inference sample is 40 seeds.

| Contrast | Mean | 98.75% CI |
|---|---:|---|
| C1 | 0.041258 | [0.036549, 0.045967] |
| C2 | -0.025069 | [-0.029815, -0.020324] |
| C3 | 0.034406 | [0.030207, 0.038606] |
| C4 | -0.067669 | [-0.078783, -0.056556] |

C1: normalized-impact raw-deviation minus score-only; C2: equal-event raw-deviation minus score-only; C3: normalized-impact raw-deviation minus occlusion; each averages platform and payload after averaging the primary five models. C4: normalized-impact occlusion-minus-score difference, payload minus platform. Expected signs are +, −, +, −. All four adjusted intervals must support their prespecified signs for the joint pattern.

The primary models are logistic regression, isolation forest, HGB, PCA, and autoencoder. The mandatory all-six-model and individual-model analyses use descriptive unadjusted 95% intervals. The decision-tree primary exclusion was fixed from discovery ties. No seed was replaced or added. Zero-capacity queues remain zero; null/opposite results remain in all summaries.

This is an internal replication within one fixed synthetic generator, not external operational validation. No smallest effect of interest was set, so practical importance, equivalence, and operational benefit are not established. Historical V4/V5 gate stops and unopened endpoints are unchanged.

## Files and reproduction

Download the four assets from release `f07-fresh-mta-results-20260920`, verify their SHA-256 values in `PUBLIC_RESULTS_MANIFEST.json`, and extract them into one new directory. Each contains a disjoint ten-seed set under `run/`; shared README/LICENSE metadata may be identical or explanatory. The manifest lists all 4,920 scientific outputs and 400 atomic checkpoint records. The exact 20 frozen sources, aggregate, and independently computed analysis tables are in this Git directory.

From this directory, run:

```bash
python reproduce_fresh_summary.py --run-dir /path/to/extracted/run
```

This requires Python, NumPy, and SciPy. It verifies the identities and exact hashes of the 40 released endpoint files against the public manifest, then recomputes their summary within absolute 2e-12 and relative 2e-11 numerical tolerances. It fits no models and evaluates no policies; it is not a byte-exact reproduction of aggregate JSON or a full raw-data rerun. The exact source snapshot retains the producer runtime and author-workflow dependencies; this public consumer has no private launch-binding dependency.

Synthetic data and fitted-model artifacts are provided in the assets; no third-party raw dataset is redistributed. The registry late-entry disclosure and administrative exclusions are explicit in the manifest.

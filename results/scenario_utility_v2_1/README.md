# V5 confirmation property-gate closure

Date/time: 2026-08-30 02:06 +03:00
Tool: Codex
Model, if known: GPT-5
Operation ID: `f07-v5-confirmation-r7-20260830`

The public-frozen V5 confirmation stopped before policy, null, construct, or
endpoint analysis. Of 3,089 frozen property checks, two failed:

- `generated_episode_at_most_one_event_seed303_pca`
- `generated_episode_at_most_one_event_seed303_ae`

Both checks trace to one seed-303, replicate-5 event cluster. A persistent alarm
episode spans samples 2510--3140 and contains three non-overlapping injected
events at 2536--2618, 2750--2918, and 2987--3080. The generator's non-overlap
rule was respected. The frozen evaluator already supports multi-event episodes
through maximum-weight one-to-one matching, so the failed predicate is
classified as a fixed gate misspecification rather than data corruption.

That diagnosis does not reopen V5. Public protocol `v2.0.0` makes any property
failure terminal. No endpoint file was created, and removing the check or
continuing with seeds 300--319 would be post-outcome rescue.

Files:

- `v5_property_tests.json`: complete 3,089-check result.
- `v5_run_manifest.json`: public-release identity and 2,241 registered artifact
  hashes.
- `v5_confirmatory_failure.json`: compact claim-safe closure and root cause.

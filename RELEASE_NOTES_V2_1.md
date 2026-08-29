# V5 property-gate outcome

Date/time: 2026-08-30 02:06 +03:00
Tool: Codex
Model, if known: GPT-5
Operation ID: `f07-v5-results-release-20260830`

This release publishes the outcome of the prospective `v2.0.0` freeze without
changing its code, plan, thresholds, seeds, or decision rules.

- Untouched confirmation seeds: 300--319.
- Property result: 3,087/3,089 checks passed.
- Failed checks: `generated_episode_at_most_one_event_seed303_pca` and
  `generated_episode_at_most_one_event_seed303_ae`.
- Shared cause: one persistent alarm episode in seed 303, test replicate 5,
  spans three non-overlapping injected events.
- Classification: `FIXED_GATE_MISSPECIFIED`; the frozen matcher already
  supports multi-event alarm episodes.
- Protocol consequence: `NOT_CONFIRMED_PROPERTY_GATE`.
- Policy, null, construct, and confirmatory endpoint analyses were not run.
- No seed/model replacement, threshold change, gate deletion, or other rescue
  was performed.

The result neither supports nor refutes the V5 scenario-reversal hypothesis.
It documents a gate-design failure under a public, hash-bound protocol.

# V5 prospective confirmation freeze

Date/time: 2026-08-30 01:38 +03:00
Tool: Codex
Model, if known: GPT-5
Operation ID: `f07-v5-public-freeze-20260830`

This release prospectively freezes the V5 replicate-pooled confirmation before
any seed 300--319 artifact is generated. It contains no V5 confirmation
outcome.

- Seven independently generated test trajectories per seed; segmentation
  occurs within each trajectory before completed episodes are pooled.
- Endpoint-blind seeds 200--209 pilot: 397/397 property checks passed.
- Five co-primary directional conditions with an intersection-union decision:
  every one-sided 95% Student-t lower bound must exceed zero.
- Fixed-mean joint power and predictive assurance both reached 0.80 at seven
  seeds; the pre-existing protocol floor retains 20 confirmation seeds.
- Confirmation is restricted to untouched seeds 300--319.
- Five-model episode-weighted pooled queue is primary. Six-model
  episode-weighted and five-model trajectory-weighted analyses are mandatory
  sensitivities and cannot upgrade the primary decision.
- Release-bound launcher verifies tag, commit, plan hash, frozen-file hashes,
  clean checkout, exact seeds, and post-release artifact times/hashes.

V4 remains `NOT_CONFIRMED_PROPERTY_GATE`; V5 does not reinterpret or rescue its
uncomputed endpoints.

plan_sha256=db0437d6c24f32e205e799e1cb1173d3c203b3f58c25f996aeea0ead3fa2b48b

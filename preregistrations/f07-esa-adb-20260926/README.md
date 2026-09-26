# Prospective freeze: ESA-ADB Mission1 bounded real-telemetry arm

Date/time: 2026-09-26T22:15:07+03:00
Tool: Cowork-Claude
Model: claude-opus-5-5 (editor)
Operation ID: f07-rb4-esa-adb-revision-20260926

This package freezes, before any full-data model fit and before any test-period window is scored, the
protocol, code and pre-freeze evidence of a bounded external arm on the public ESA Anomalies Dataset
(Mission1; Zenodo record 15237121, version v2; CC BY 3.0 IGO). The arm asks whether explanation-free channel
masses rank the channels annotated as affected by a detected event within a prespecified non-inferiority
margin (0.06 AUROC) of the detectors' native explanations, and how false-alarm channel mass concentrates.
Annotated affected channels are not causal drivers; no mission-harm or operator-utility claim is made.

Raw data disposition: the raw archive `ESA-Mission1.zip` (3,776,246,073 bytes; MD5
`9770ad12ed730238f37c42d5c27ab436`; SHA-256
`ba28f761b1deab4dbba4728793bff139fea39dbf9cf0d9c559d619ffe75d5a72`) is deliberately not included in this
repository. It is public at https://zenodo.org/records/15237121 (version v2, 2025-04-17) and downloadable
without registration; the CC BY 3.0 IGO licence was observed on the record page at download on 2026-09-26.
The exclusion was decided with the arm itself (project decision D11-a, 2026-09-26).

Freeze contract SHA-256: `d07fac7fc1a50eed09be37b4d645c7559c1dec5683a96098c123770ae4ee78b3`.
Final protocol SHA-256: `bb15984da89c7763f3d0be44a02c5b758330207ecdd26b05ef274312fdcaed52` (version 3.0-final).
Run: `2026-09-26_claude_isyeri_notebook_esa_adb_mission1_arm`.

Lineage: candidate v3 (experiments/.../ESA_ADB_PROTOCOL_CANDIDATE_V3.json) -> independent delta review
(REVIEW.json, a different model than the editor) -> editor decision (DECISION.json) -> FINAL.json; the
schema-3 contract binds all four by SHA-256. The earlier independent review of v2 and its finding-by-finding
disposition are included. The executing code is `code_snapshot/`; the runner refuses a full-data fit unless
the executing files match these hashes. Property tests PT1-PT3 passed before the freeze; PT1 reports hashes
only because its bounded smoke subset scored test-period windows that stay quarantined.

Files marked as projections in PUBLIC_PACKAGE_MANIFEST.json differ from their private originals only by the
listed replacement of local path prefixes and of the physical host name; the original SHA-256 of each is
recorded. No scientific result of this arm exists at publication time. Negative, null, NOT_INFORMATIVE and
NOT_EVALUABLE outcomes remain reportable and no rescue analysis is permitted.

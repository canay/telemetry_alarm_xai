# Closure check: application of the ESA-ADB delta review (D-01 to D-05)

- Check ID: F07-ESA-ADB-F1-DELTA-CLOSURE-CHECK
- Checker: claude-fable-5-1 (independent closure checker; not the editor)
- Checked at: 2026-09-26T21:55:28+03:00
- Operation: f07-rb4-esa-adb-revision-20260926
- Delta review: `f1_review/DELTA_REVIEW.json`, SHA-256 `A73BFD8C104A1B19D85C43C37D9CA54BE8114EFDA7BF1099AAB7FC2F2660F05A` (equals `expected_review_sha256` in the decision spec)
- Candidate: `ESA_ADB_PROTOCOL_CANDIDATE_V3.json`, SHA-256 `DCE48A36D693A843DE08582908907BF340DEB1E457276DB257C9179C2CB8B03A` (equals the delta review's and the preview's value)
- Decision spec: `f1_review/DECISION_SPEC_20260926.json`, SHA-256 `694A92DADDBCC309CDE047AE15273C5B253E9DEFC2E044BC83666ECC1678BACA`

## Verdict

**CLOSED_WITH_NOTES.** All five items are CLOSED. Findings: P0 0, P1 0, P2 0, P3 1 (housekeeping, not blocking).

## Hashes

| File | `code_delta_reviewed_20260926/` (recomputed) | `src/` (recomputed) |
|---|---|---|
| esa_core.py | `7206F9587AC34FE2C94095EE828AE8CA328550DA75017B3A6604A0E6C1B85B24` | `C9ED54434FEE8D9E84BDB26177ECFBB5B28EF58F600DD5A6400B9348EB2F1732` |
| esa_arm.py | `60D50EA9CA18867392225D5712F23C98794887C835A98EA898DD89E99D48E171` | `938EBCE51A5C39D4A0DA4ACFAA87288E23FF695568AD23230AB926CCCF528FD5` |
| esa_property_tests.py | `78EA2DA958533C8026E58739211E569770E3707B2689D6E631B4F27B7E7BD662` | `78EA2DA958533C8026E58739211E569770E3707B2689D6E631B4F27B7E7BD662` |

The reviewed-copy hashes equal `code_sha256` in DELTA_REVIEW.json. The `src/` hashes equal `fixed_sha256` in POST_REVIEW_FIXES_CHECK.json. The property-test file is byte-identical in both copies.

## My diff of the reviewed copy against `src/`

`git diff --no-index` (two lines of context) is line-for-line the editor's `POST_REVIEW_FIXES_20260926.diff`:

- `esa_core.py`: one line, `keep = e2 > s2` becomes `keep = e2 >= s2` in `clip_intervals` (line 618).
- `esa_arm.py`: three lines removed and six added, all inside `unit_eval`: the accumulator `ep_rows_all` becomes `ep_frames` (line 940); `model_rows = []` before the episode loop (1082); `model_rows.append(row)` (1094); `ep_frames.append(pd.DataFrame(model_rows))` and `del model_rows` after the loop (1095-1096); the write becomes `pd.concat(ep_frames, ignore_index=True) if ep_frames else pd.DataFrame()` (1139).
- `esa_property_tests.py`: no change.

All six files are LF-only with no BOM and a trailing newline. The three `src/` files compile (in-memory compile, no bytecode written). An AST comparison of every top-level node finds `clip_intervals` (of 88 nodes) and `unit_eval` (of 74 nodes) as the only changed definitions. Nothing else changed.

## Scope

`clip_intervals` is called only at `esa_core.py` lines 660 and 673, inside `vor_corrected_event_wise`, which is called only at `esa_arm.py` lines 1011-1012, inside `unit_eval`. The identifiers `ep_rows_all`, `ep_frames` and `model_rows` occur only inside `unit_eval`. `esa_property_tests.py` never reaches these functions: PT1 filters out eval and decision units (line 121), PT2 runs prep units and PT3 reads standardization outputs. The prep and stdz checkpoints and PT1-PT3 are therefore unaffected by both changes.

## Items

### D-01 (blocking): CLOSED

Both `esa_core.py` copies were loaded from disk in a scratch directory (no bytecode written) and compared on toy cases and against an independent brute-force implementation of the protocol's `E4_vor_corrected_event_wise` definitions (closed-interval overlap for TPe, FNe and FPe; durations for FPt and Nt).

| Case | Fixed (src) | Reviewed copy |
|---|---|---|
| Reviewer's toy: alarms [150,250], [300,350], [690,710], [900,950]; events [100,200], [400,450], point 700; t0 0, t1 1000 | TPe 2, FNe 1, FPe 2, FPt 170 s, Nt 850 s, Pre 0.40 | FPe 3, Pre 0.32 (other quantities equal) |
| Point event at t0 (0) with alarm [0,20]; event [500,600] with alarm [550,570] | TPe 2, FNe 0, FPe 0, FPt 20 s, Nt 900 s | FPe 1 |
| Point event at t1 (1000) with alarm [990,1010]; event [500,600] undetected | TPe 1, FNe 1, FPe 0, FPt 10 s, Nt 900 s | FPe 1 |
| Alarm [690,700] touching a point event at 700 at its end | TPe 1, FNe 0, FPe 0, FPt 10 s, Nt 1000 s | FPe 1 |
| Alarm [700,720] touching a point event at 700 at its start | TPe 1, FNe 0, FPe 0, FPt 20 s, Nt 1000 s | FPe 1 |
| Excluded (rare) point event only, alarm [690,710]; event [100,200] undetected | TPe 0, FNe 1, FPe 0, FPt 20 s, Nt 900 s | FPe 1 |
| Zero-duration event with point segments 310 and 400; alarms [300,320], [395,405] | TPe 1, FNe 0, FPe 0, FPt 30 s, Nt 1000 s | FPe 2 |
| Point at 200 touching event [100,200]; alarm [150,250] | TPe 1, FNe 0, FPe 0, FPt 50 s, Nt 900 s | identical |
| Points outside the test period (-5, 1005); alarm [0,10] | TPe 0, FNe 2, FPe 1, FPt 10 s, Nt 1000 s | identical (out-of-range points stay dropped) |
| No alarms | TPe 0, FNe 2, FPe 0, FPt 0 s, Nt 900 s | identical |

The reviewer's toy numbers equal those in POST_REVIEW_FIXES_CHECK.json. In every case the fixed function gives the protocol's FPe (episodes overlapping no included and no excluded event), and TPe, FNe, FPt and Nt are identical between the copies. Over 3,000 random cases the fixed function equals the brute-force reference on all five quantities; TPe, FNe, FPt and Nt are identical between the copies in every case; FPe differs in 640 cases, always reviewed greater than fixed, and only when a zero-length segment exists after clipping (a raw point event, or a segment clipped to a point at the test-period boundary). `clip_intervals` has no other caller.

### D-02: CLOSED

The change is exactly the required per-model frame list with concatenation at write time and an empty frame when no model has episodes. A model without episodes leaves the model loop at line 1061 before any frame is built, just as it left before any row was appended in the reviewed code; light-set models append their frame before the `set_name != "primary"` continue at line 1109.

CSV bytes were written with the same call as `atomic_csv` (`frame.to_csv(path, index=False)`; Python 3.12.7, pandas 2.3.3, numpy 2.3.5) for `pd.DataFrame(all_rows)` versus `pd.concat(frames, ignore_index=True)` on rows mirroring the `unit_eval` row construction (14 base keys plus `top_<kind>_<source>` and `_guarded` keys with per-row availability). Bytes were identical for: a realistic six-model table (170 rows, capped native and occlusion keys, dtree without `aggregated_native`, hgb without episodes); a key first present in the last row of the last model; a column absent from every row of one model; mixed availability; a single model; one episode per model; no episodes in any model (2 bytes in both); and 300 random tables with random per-model key availability including 0 and 1. No pandas warning was emitted.

### D-03: CLOSED

The preview's `old` for `/execution/code_snapshot` equals the current candidate value; `new` equals the decision spec's final value. `new` equals `old` plus a space plus the reviewer's sentence, with exactly one insertion: "and the two evaluation-only changes required by the delta review (D-01: clip_intervals keeps zero-length event segments; D-02: unit_eval builds episode rows as per-model frames; f1_review/POST_REVIEW_FIXES_20260926.diff, verified in POST_REVIEW_FIXES_CHECK.json and in the independent closure check f1_review/CLOSURE_CHECK.json)" placed between "the delta review)" and "produced the frozen code". The three pre-refactor hashes, the refactor diff and check references and the `ESA_ADB_RAW_ROOT` clause are verbatim. The extension is acceptable and necessary: after D-01 and D-02 the refactor alone no longer produces the frozen code, both descriptions are accurate, and the reference to CLOSURE_CHECK.json is satisfied by this check. The disposition asserts that the diff and check files are in the freeze package; the package is outside this check's whitelist.

### D-04: CLOSED

`/endpoints/E4`: `old` equals the candidate value; `new` equals `old` plus a space plus the required sentence, verbatim, and equals the decision spec's final value. The sentence matches `unit_eval` lines 1005-1006 (positives are event-labeled windows, negatives the other windows of `~gap_mask_test | event_window_label`). No code change, as required.

### D-05: CLOSED

`/public_freeze/when`: the phrase "and the PT1-PT3 smoke on the bounded 2006-07-01..2007-06-30 subset may precede the freeze" occurs exactly once in `old`, and `new` is `old` with that phrase replaced by "and the property tests PT1 (smoke on the bounded 2006-07-01..2007-06-30 subset), PT2 and PT3 may precede the freeze", verbatim.

`/property_tests_fail_closed_before_freeze/PT1_test_label_independence`: "one replicate" occurs once; `new` is `old` with ", N_fit = 20,000 and N_bg = 5,000 for the smoke" inserted before the closing parenthesis of the existing parenthesis, content verbatim. A literal insertion would have read "... one replicate (N_fit = 20,000 and N_bg = 5,000 for the smoke))", so the placement inside the existing parenthesis is acceptable.

Both `old` values equal the candidate values and both `new` values equal the decision spec's final values. A recursive scan of the candidate finds "PT1-PT3 smoke" and "smoke on the bounded" only in `public_freeze.when`, so no other field carries the slip.

## Dispositions

DECISION_SPEC_20260926.json lists D-01 to D-05 exactly once each, all ACCEPT_APPLIED, with rationales consistent with the applied code and text. Its `code_changes` name the two files and its `code_change_evidence` names the reviewed copy, the diff, the editor's check and this closure check. Its `final_changes` carry the four preview `new` values unchanged.

## Findings

**C-01 (P3, not blocking) - stray bytecode in the reviewed-code evidence folder.** The editor's `src/verify_post_review_fixes.py` imports both `esa_core.py` copies through importlib, which wrote a `__pycache__` directory into `code_delta_reviewed_20260926/` (directory timestamp 2026-09-26 21:38:58, the script's run time). Harmless: the three `.py` files keep the delta review's hashes and the diff ignores it. Required change: housekeeping only, remove or exclude `__pycache__` from that folder before it is packaged. No change to code, protocol or dispositions.

## Checks performed

- SHA-256 recomputed for the delta review, the three reviewed files, the three `src/` files, the candidate and the decision spec (values above); cross-checked against DELTA_REVIEW.json, POST_REVIEW_FIXES_CHECK.json, FINAL_TEXT_EDITS_PREVIEW.json and DECISION_SPEC_20260926.json.
- Own unified diff of the reviewed copy against `src/`, line-ending and BOM check, in-memory compile, AST comparison of every top-level node.
- Caller search over `src/esa_*.py` for `clip_intervals`, `vor_corrected_event_wise` and the episode-row identifiers; property-test unit selection read from `esa_property_tests.py`.
- D-01: 10 toy cases and 3,000 random cases on both copies against a brute-force reference of the protocol definitions.
- D-02: CSV byte equality for 7 constructed tables and 300 random tables, warnings captured.
- Protocol edits: JSON-pointer resolution of the four fields, equality of `old` with the candidate and of `new` with the decision spec, character-level opcodes, comparison with the required wording parsed from DELTA_REVIEW.json, recursive phrase scan.
- Editor's POST_REVIEW_FIXES_CHECK.json values cross-checked against my own scratch runs without executing the editor's script.

## Checks not run

- `verify_post_review_fixes.py`, `esa_arm.py` and `esa_property_tests.py` were not executed (prohibited; the verify script rewrites evidence files).
- `src/build_freeze.py` and the freeze package are outside the whitelist: whether the four replacements reach the frozen protocol exactly as previewed, the declared `execution.host` pseudonymization and FINAL metadata edits, and the inclusion of the refactor and post-review diff, check and closure files in the package remain to be verified at freeze time.
- No real data read; `unit_eval` not run on real episode files. D-02 equivalence is shown on synthetic rows under the interpreter on this host.
- The official ESA-ADB metric implementation was not consulted (no network); D-01 is assessed against the protocol's own definitions.
- PATH_REFACTOR_20260926.diff, PATH_REFACTOR_CHECK.json and the unit checkpoints (the factual basis of the D-03 sentence) were not re-read; outside the whitelist and already verified by the delta review.

## Summary

All five required changes are applied faithfully. My diff of the reviewed copy against `src/` is exactly D-01 (one line) and D-02 (nine lines in `unit_eval`); nothing else changed and the property-test file is byte-identical. Both changes are reached only from `unit_eval`, so prep/stdz checkpoints and PT1-PT3 are unaffected. The four protocol edits carry the required wording verbatim, with an accurate D-03 extension and an acceptable D-05 placement. One P3 housekeeping note.

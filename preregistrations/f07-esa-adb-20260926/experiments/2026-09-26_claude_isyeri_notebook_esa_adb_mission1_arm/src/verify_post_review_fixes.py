"""Verify the two post-review code fixes (delta review D-01 and D-02) of the ESA-ADB Mission1 arm.

Operation: f07-rb4-esa-adb-revision-20260926 (editor tooling; not part of the frozen pipeline code).
Compares src/ with the delta-reviewed copy in code_delta_reviewed_20260926/, writes the unified diff to
f1_review/POST_REVIEW_FIXES_20260926.diff and the result to f1_review/POST_REVIEW_FIXES_CHECK.json.
Checks: (1) the diff consists exactly of the expected removed and added lines; (2) both files compile and keep
LF line endings; (3) D-01 on the reviewer's toy case: the fixed vor_corrected_event_wise returns FPe 2 and
Pre 0.40, and the reviewed (unfixed) function returns FPe 3 and Pre 0.32 (positive control that the test
distinguishes the two); (4) D-02: the per-model DataFrame concatenation writes the same CSV bytes as the
single list-of-dicts DataFrame on synthetic rows with late-appearing and missing keys, a model without
episodes, bool/NaN mixes, and the all-empty case. Runs no pipeline unit and reads no data.
"""
from __future__ import annotations

import difflib
import hashlib
import importlib.util
import io
import json
import py_compile
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

RUN = Path(__file__).resolve().parents[1]
REVIEWED = RUN / "code_delta_reviewed_20260926"
SRC = RUN / "src"
FILES = ("esa_core.py", "esa_arm.py", "esa_property_tests.py")
EXPECTED = {
    "esa_core.py": {"removed": ["    keep = e2 > s2"], "added": ["    keep = e2 >= s2"]},
    "esa_arm.py": {
        "removed": ["    e1_rows, det_rows, year_rows, sub_rows, ep_rows_all, e2_rows, e3_rows, e3_summary = [], [], [], [], [], [], [], []",
                    "            ep_rows_all.append(row)",
                    "    atomic_csv(outs[6], pd.DataFrame(ep_rows_all))"],
        "added": ["    e1_rows, det_rows, year_rows, sub_rows, ep_frames, e2_rows, e3_rows, e3_summary = [], [], [], [], [], [], [], []",
                  "        model_rows = []",
                  "            model_rows.append(row)",
                  "        ep_frames.append(pd.DataFrame(model_rows))",
                  "        del model_rows",
                  "    atomic_csv(outs[6], pd.concat(ep_frames, ignore_index=True) if ep_frames else pd.DataFrame())"]},
    "esa_property_tests.py": {"removed": [], "added": []},
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def csv_bytes(frame: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    frame.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def main() -> int:
    result = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "tool": "Cowork-Claude",
              "model": "claude-opus-5-5 (editor)", "operation_id": "f07-rb4-esa-adb-revision-20260926",
              "reviewed_sha256": {n: sha(REVIEWED / n) for n in FILES}, "fixed_sha256": {n: sha(SRC / n) for n in FILES},
              "checks": {}}
    diff_text = []
    ok = True
    for n in FILES:
        a = (REVIEWED / n).read_bytes().decode("utf-8").splitlines()
        b = (SRC / n).read_bytes().decode("utf-8").splitlines()
        d = list(difflib.unified_diff(a, b, fromfile=f"code_delta_reviewed_20260926/{n}", tofile=f"src/{n}",
                                      n=2, lineterm=""))
        diff_text += d
        removed = [x[1:] for x in d if x.startswith("-") and not x.startswith("---")]
        added = [x[1:] for x in d if x.startswith("+") and not x.startswith("+++")]
        match = removed == EXPECTED[n]["removed"] and added == EXPECTED[n]["added"]
        raw = (SRC / n).read_bytes()
        eol_lf_only = b"\r" not in raw
        py_compile.compile(str(SRC / n), doraise=True)
        result["checks"][f"diff_{n}"] = {"removed": removed, "added": added, "matches_expected": match,
                                         "lf_only": eol_lf_only, "compiles": True}
        ok &= match and eol_lf_only
    (RUN / "f1_review" / "POST_REVIEW_FIXES_20260926.diff").write_bytes(("\n".join(diff_text) + "\n").encode("utf-8"))

    # D-01 toy case from the delta review (seconds -> ns)
    ns = 10 ** 9
    fixed = load("esa_core_fixed", SRC / "esa_core.py")
    old = load("esa_core_reviewed", REVIEWED / "esa_core.py")
    alarm_s = np.asarray([150, 300, 690, 900], dtype=np.int64) * ns
    alarm_e = np.asarray([250, 350, 710, 950], dtype=np.int64) * ns
    segs = [[(100 * ns, 200 * ns)], [(400 * ns, 450 * ns)], [(700 * ns, 700 * ns)]]
    inc = np.ones(3, dtype=bool)
    all_s = np.asarray([100, 400, 700], dtype=np.int64) * ns
    all_e = np.asarray([200, 450, 700], dtype=np.int64) * ns
    rf = fixed.vor_corrected_event_wise(alarm_s, alarm_e, segs, inc, all_s, all_e, 0, 1000 * ns)
    ro = old.vor_corrected_event_wise(alarm_s, alarm_e, segs, inc, all_s, all_e, 0, 1000 * ns)
    d01 = {"fixed": rf, "reviewed": ro,
           "fixed_expected": rf["TPe"] == 2 and rf["FNe"] == 1 and rf["FPe"] == 2 and abs(rf["Pre"] - 0.40) < 1e-12,
           "reviewed_expected": ro["FPe"] == 3 and abs(ro["Pre"] - 0.32) < 1e-12,
           "fpt_nt_unchanged": rf["FPt_s"] == ro["FPt_s"] and rf["Nt_s"] == ro["Nt_s"]}
    result["checks"]["D-01_toy"] = d01
    ok &= d01["fixed_expected"] and d01["reviewed_expected"] and d01["fpt_nt_unchanged"]

    # D-02 equivalence on synthetic episode rows
    rng = np.random.default_rng(7)
    models = [("lr", 40, True), ("dtree", 0, False), ("iforest", 25, False), ("pca", 60, True)]
    all_rows, frames = [], []
    for name, n_ep, closed in models:
        rows = []
        for k in range(n_ep):
            row = {"set": "primary", "model": name, "episode": k, "start_window": int(rng.integers(0, 10 ** 6)),
                   "tau": float(rng.random()), "fa": bool(rng.random() < 0.5), "n_events": int(rng.integers(0, 3)),
                   "subperiod": "drift" if rng.random() < 0.3 else "pre_drift", "peak_stale": bool(rng.random() < 0.1)}
            if k % 3 != 0:  # late-appearing / missing key, as for capped occlusion rows
                row["top_peak_occlusion"] = f"channel_{int(rng.integers(1, 76))}"
                row["top_peak_occlusion_guarded"] = bool(rng.random() < 0.2)
            row["top_peak_raw"] = f"channel_{int(rng.integers(1, 76))}"
            if closed:
                row["top_aggregated_native"] = f"channel_{int(rng.integers(1, 76))}"
            rows.append(row)
        if n_ep == 0:
            continue  # unit_eval skips a model without episodes before its row loop
        all_rows += rows
        frames.append(pd.DataFrame(rows))
    old_bytes = csv_bytes(pd.DataFrame(all_rows))
    new_bytes = csv_bytes(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    empty_old = csv_bytes(pd.DataFrame([]))
    empty_new = csv_bytes(pd.DataFrame())
    d02 = {"rows": len(all_rows), "bytes_equal": old_bytes == new_bytes, "sha_old": hashlib.sha256(old_bytes).hexdigest(),
           "sha_new": hashlib.sha256(new_bytes).hexdigest(), "empty_case_equal": empty_old == empty_new,
           "header": old_bytes.split(b"\n", 1)[0].decode()}
    result["checks"]["D-02_equivalence"] = d02
    ok &= d02["bytes_equal"] and d02["empty_case_equal"]
    result["verdict"] = "POST_REVIEW_FIXES_VERIFIED" if ok else "POST_REVIEW_FIXES_FAILED"
    (RUN / "f1_review" / "POST_REVIEW_FIXES_CHECK.json").write_bytes(
        (json.dumps(result, indent=1, default=str) + "\n").encode("utf-8"))
    print(json.dumps({"verdict": result["verdict"], "fixed_sha256": result["fixed_sha256"],
                      "d01": {k: v for k, v in d01.items() if k != "fixed" and k != "reviewed"},
                      "d02": {k: d02[k] for k in ("rows", "bytes_equal", "empty_case_equal")}}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

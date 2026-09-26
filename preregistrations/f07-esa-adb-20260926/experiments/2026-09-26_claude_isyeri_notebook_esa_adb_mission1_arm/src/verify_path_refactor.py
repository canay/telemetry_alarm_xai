"""Verify that the path-only refactor of esa_arm.py / esa_property_tests.py changes no resolved path or output.

Operation: f07-rb4-esa-adb-revision-20260926
Checks, all fail-closed:
  1. unified diff of the pre-refactor code (code_prerefactor_20260926/) against src/ touches only the path lines;
  2. default_config() of both versions, each run in its own interpreter, resolves byte-identical field values;
  3. `esa_arm.py plan` prints the same unit plan under both versions;
  4. the refactored unit_prep reproduces the recorded prep outputs of channel_12, channel_41 and channel_61
     byte for byte (sha256 equal to the unit checkpoints written by the pre-refactor code), writing only into a
     fresh scratch work folder; no label is read (prep is label-free).
Writes f1_review/PATH_REFACTOR_20260926.diff and f1_review/PATH_REFACTOR_CHECK.json.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
OLD = RUN / "code_prerefactor_20260926"
NEW = RUN / "src"
FILES = ("esa_arm.py", "esa_core.py", "esa_property_tests.py")
CHANNELS = ("channel_12", "channel_41", "channel_61")
DUMP = r"""
import json, sys
from dataclasses import fields
sys.path.insert(0, sys.argv[1])
import esa_arm as A
cfg = A.default_config()
out = {f.name: (str(getattr(cfg, f.name)) if f.name not in ("channel_sets", "models", "timeouts", "extra")
                else getattr(cfg, f.name)) for f in fields(cfg)}
print(json.dumps(out, sort_keys=True))
"""


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def main() -> int:
    result = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "operation_id": "f07-rb4-esa-adb-revision-20260926", "tool": "Cowork-Claude", "model": "claude-opus-5-5",
              "pre_refactor_sha256": {n: sha(OLD / n) for n in FILES},
              "post_refactor_sha256": {n: sha(NEW / n) for n in FILES}}
    # 1. diff
    diff_text = []
    changed_lines = {}
    for n in FILES:
        a = (OLD / n).read_text(encoding="utf-8").splitlines(keepends=True)
        b = (NEW / n).read_text(encoding="utf-8").splitlines(keepends=True)
        d = list(difflib.unified_diff(a, b, fromfile=f"code_prerefactor_20260926/{n}", tofile=f"src/{n}"))
        diff_text.extend(d)
        changed_lines[n] = [ln.rstrip("\n") for ln in d if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    assert not changed_lines["esa_core.py"], "esa_core.py must be unchanged"
    allowed = ("RAW_ROOT", "run_dir", "project", "ESA_ADB_RAW", "Path(__file__)", "RUN =", "WORK =", "assert RUN.name",
               "raise RuntimeError(f\"run folder", "# Path-only refactor", "# archive root", "# project path",
               "if run_dir.name", "zip_path=", "work=RAW_ROOT", "work=Path(")
    for n, lines in changed_lines.items():
        for ln in lines:
            body = ln[1:].strip()
            assert any(tok in body for tok in allowed), f"non-path change in {n}: {ln}"
    (RUN / "f1_review" / "PATH_REFACTOR_20260926.diff").write_bytes("".join(diff_text).encode("utf-8"))
    result["diff_changed_lines"] = {n: len(v) for n, v in changed_lines.items()}
    # 2. resolved configuration
    dumps = {}
    for tag, folder in (("pre", OLD), ("post", NEW)):
        env = dict(os.environ)
        env.pop("ESA_ADB_RAW_ROOT", None)
        r = subprocess.run([sys.executable, "-c", DUMP, str(folder)], capture_output=True, text=True, env=env, check=True)
        dumps[tag] = json.loads(r.stdout)
    diffs = {k: (dumps["pre"][k], dumps["post"][k]) for k in dumps["pre"] if dumps["pre"][k] != dumps["post"][k]}
    assert not diffs, f"resolved configuration differs: {diffs}"
    assert dumps["post"]["run_dir"] == str(RUN), dumps["post"]["run_dir"]
    result["resolved_config_identical"] = True
    result["resolved_paths"] = {k: dumps["post"][k] for k in ("zip_path", "meta_dir", "work", "run_dir", "freeze_record")}
    # 3. unit plan (esa_arm.py plan writes UNIT_PLAN.json into the run folder and prints the unit count)
    plan_file = RUN / "UNIT_PLAN.json"
    before = sha(plan_file) if plan_file.exists() else None
    plans = {}
    for tag, folder in (("pre", OLD), ("post", NEW)):
        r = subprocess.run([sys.executable, str(folder / "esa_arm.py"), "plan"], capture_output=True, text=True, check=True)
        plans[tag] = (r.stdout.strip(), plan_file.read_bytes())
    assert plans["pre"] == plans["post"] and plans["post"][0] == "147", "unit plan differs"
    result["plan_identical"] = True
    result["unit_plan_sha256"] = sha(plan_file)
    result["unit_plan_sha256_before_check"] = before
    # 4. prep byte-equivalence on three channels into a scratch work folder
    sys.path.insert(0, str(NEW))
    import esa_arm as A  # noqa: E402

    class _Runner:
        def phase(self, name):
            pass

    cfg = A.default_config()
    real_work = cfg.work
    scratch = Path(tempfile.mkdtemp(prefix="esa_path_refactor_"))
    try:
        shutil.copy2(real_work / "grid.json", scratch / "grid.json")
        cfg.work = scratch
        prep = {}
        for ch in CHANNELS:
            ck = json.loads((RUN / "units" / f"prep__{ch}.json").read_text(encoding="utf-8"))
            recorded = {Path(o["path"]).name: o["sha256"].upper() for o in ck["outputs"]}
            A.unit_prep(cfg, _Runner(), ch)
            got = {p.name: sha(p) for p in A.prep_paths(cfg, ch)}
            assert got == recorded, (ch, got, recorded)
            prep[ch] = got
        result["prep_recomputed_byte_identical"] = prep
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    result["verdict"] = "PATH_ONLY_REFACTOR_VERIFIED"
    (RUN / "f1_review" / "PATH_REFACTOR_CHECK.json").write_bytes(json.dumps(result, indent=1).encode("utf-8"))
    print(json.dumps({k: result[k] for k in ("diff_changed_lines", "resolved_config_identical", "plan_identical",
                                             "verdict")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

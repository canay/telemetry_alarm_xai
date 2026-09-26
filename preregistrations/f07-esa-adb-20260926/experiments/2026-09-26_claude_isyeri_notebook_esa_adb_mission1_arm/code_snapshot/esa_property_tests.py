"""Fail-closed property tests PT1-PT3 for the ESA-ADB Mission1 bounded arm (protocol v3; no test-label reading).

Operation: f07-rb4-esa-adb-revision-20260926

  python esa_property_tests.py pt2     label-free preprocessing (3 channels, full grid)
  python esa_property_tests.py pt1     test-label independence of every pre-evaluation stage (smoke subset,
                                       all six families, one replicate); outputs QUARANTINED
  python esa_property_tests.py pt3     invariants on the full-run standardization outputs (both sets)

PT1 edits the TEST-period rows of the label table only for its variants; the pipeline under test
must filter them out before any stage uses labels, so all pre-evaluation artifacts must be
byte-identical. PT1 prints and records only file hashes and pass/fail: the smoke's scores,
thresholds, flag rates, episode counts and masses are quarantined and are not inspected before
the public freeze (protocol v3, public_freeze.when). Neither test computes an evaluation metric.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import esa_arm as A  # noqa: E402
import esa_core as C  # noqa: E402

RUN = Path(__file__).resolve().parents[1]  # path-only refactor: same folder on the author host, no embedded path
assert RUN.name == A.RUN_ID, RUN.name
PT = RUN / "property_tests"
WORK = A.RAW_ROOT / "work" / "pt"
QUARANTINE_NOTE = ("QUARANTINED (protocol v3): this smoke directory holds scores, thresholds, flag rates, "
                   "episode counts and masses of a bounded subset that includes test-period windows. Do not open "
                   "its units/*.json, logs or work files before the public freeze; PT1_RESULT.json carries only hashes.")


def write(path: Path, obj) -> None:
    A.atomic_json(path, obj)
    print(json.dumps(obj, indent=1, default=str)[:3000], flush=True)


def base_cfg(tag: str, **kw) -> A.Config:
    cfg = A.default_config()
    cfg.work = WORK / tag
    cfg.run_dir = PT / tag
    cfg.require_freeze = False  # property-test smoke only; the real run keeps the freeze gate
    cfg.timeouts = {}
    for key, value in kw.items():
        setattr(cfg, key, value)
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    (cfg.run_dir / "f3_schema").mkdir(parents=True, exist_ok=True)
    for name in ("F3_FACTS.json", "channel_sampling.csv"):
        shutil.copy2(RUN / "f3_schema" / name, cfg.run_dir / "f3_schema" / name)
    return cfg


def pt2() -> int:
    chans = ["channel_12", "channel_41", "channel_61"]
    real = base_cfg("pt2_real")
    blank_meta = WORK / "pt2_blank_meta"
    blank_meta.mkdir(parents=True, exist_ok=True)
    for name in ("anomaly_types.csv", "channels.csv", "telecommands.csv"):
        shutil.copy2(real.meta_dir / name, blank_meta / name)
    (blank_meta / "labels.csv").write_text("ID,Channel,StartTime,EndTime\n", encoding="utf-8")
    blank = base_cfg("pt2_blank", meta_dir=blank_meta)
    hashes = {}
    for tag, cfg in (("real", real), ("blank", blank)):
        runner = A.Runner(cfg)
        for ch in chans:
            runner.execute(f"prep:{ch}", lambda ch=ch, cfg=cfg, runner=runner: A.unit_prep(cfg, runner, ch),
                           lambda ch=ch, cfg=cfg: A.prep_paths(cfg, ch))
        hashes[tag] = {str(p.name): A.sha256_file(p) for ch in chans for p in A.prep_paths(cfg, ch)}
    ok = hashes["real"] == hashes["blank"] and len(hashes["real"]) == 3 * len(chans)
    write(PT / "PT2_RESULT.json", {"test": "PT2_label_free_preprocessing", "protocol": "v3", "channels": chans,
                                    "artifacts_per_channel": ["feat.f32", "valid.u1", "age.f32"], "pass": ok,
                                    "hashes": hashes,
                                    "note": "a label read in prep would fail the CRC check of the blank table"})
    return 0 if ok else 2


def edited_label_tables(meta_dir: Path, zip_path: Path) -> tuple[dict[str, Path], int]:
    labels = C.load_meta_table(meta_dir, zip_path, "labels.csv")
    start = pd.to_datetime(labels["StartTime"], utc=True).dt.tz_localize(None)
    test_rows = start.astype("int64").to_numpy() >= C.TEST_START_NS
    d = WORK / "pt1_tables"
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    true_p = d / "labels_true.csv"
    labels.to_csv(true_p, index=False)
    out["true"] = true_p
    rem_p = d / "labels_test_removed.csv"
    labels[~test_rows].to_csv(rem_p, index=False)
    out["test_removed"] = rem_p
    shuffled = labels.copy()
    rng = np.random.default_rng(20260926)
    idx = np.flatnonzero(test_rows)
    perm_ch = rng.permutation(len(idx))
    perm_pair = rng.permutation(len(idx))
    ch_vals = shuffled.loc[idx, "Channel"].to_numpy().copy()
    pair_vals = shuffled.loc[idx, ["StartTime", "EndTime"]].to_numpy().copy()
    shuffled.loc[idx, "Channel"] = ch_vals[perm_ch]
    shuffled.loc[idx, ["StartTime", "EndTime"]] = pair_vals[perm_pair]  # pairs move as whole values
    sh_p = d / "labels_test_shuffled.csv"
    shuffled.to_csv(sh_p, index=False)
    out["test_shuffled"] = sh_p
    return out, int(test_rows.sum())


def pt1() -> int:
    grid = (int(pd.Timestamp("2006-07-01T00:00:00").value), int(pd.Timestamp("2007-06-30T00:00:00").value))
    ref = A.default_config()
    tables, n_test_rows = edited_label_tables(ref.meta_dir, ref.zip_path)
    results = {}
    for tag, table in tables.items():
        cfg = base_cfg(f"pt1_{tag}", grid_override=grid, models=list(C.MODELS), reps=1, n_fit=20_000, n_bg=5_000,
                       labels_csv=table, channel_sets={"primary": ref.channel_sets["primary"]})
        (cfg.run_dir / "QUARANTINE_README.txt").write_text(QUARANTINE_NOTE + "\n", encoding="utf-8")
        runner = A.Runner(cfg)
        units = [u for u in A.plan_units(cfg) if not u[0].startswith(("eval:", "decision"))]
        runner.planned = len(units)
        for unit_id, fn, outs in units:
            runner.execute(unit_id, lambda fn=fn, runner=runner: fn(runner), outs)
        files = {}
        for unit_id, _, outs in units:
            for p in outs():
                files[f"{unit_id}|{p.name}"] = A.sha256_file(p)
        results[tag] = files
    keys = set(results["true"])
    same = all(set(v) == keys for v in results.values()) and all(
        results[t][k] == results["true"][k] for t in results for k in keys)
    diffs = sorted({k for t in results for k in keys if results[t].get(k) != results["true"].get(k)})
    families = sorted({k.split("|")[0].split(":")[2] for k in keys if k.startswith(("fit:", "episodes:", "attr_episode:"))})
    write(PT / "PT1_RESULT.json", {"test": "PT1_test_label_independence", "protocol": "v3", "pass": bool(same),
                                   "variants": list(tables), "test_rows_edited": n_test_rows,
                                   "compared_artifacts": len(keys), "families_covered": families,
                                   "differing_artifacts": diffs,
                                   "smoke_grid": [str(pd.Timestamp(grid[0])), str(pd.Timestamp(grid[1]))],
                                   "replicates": 1, "quarantine": QUARANTINE_NOTE,
                                   "artifact_sha256_true_variant": dict(sorted(results["true"].items())),
                                   "table_sha256": {t: A.sha256_file(p) for t, p in tables.items()}})
    return 0 if same else 2


def pt3() -> int:
    cfg = A.default_config()
    checks = {}
    ok = True
    for set_name, chans in cfg.channel_sets.items():
        geo, Z, meta, stale = A.load_set(cfg, set_name)
        nch = len(chans)
        nwin = geo["n_windows"]
        expect = (geo["n_grid"] - C.W) // C.STRIDE + 1
        valid = meta["valid"]
        guard = meta["feat_guard"]
        bad = 0
        guard_violations = 0
        cols = [fi * nch + ci for fi in range(C.NFEAT) for ci in range(nch) if guard[fi, ci]]
        for r0 in range(0, nwin, 200_000):
            rows = np.asarray(Z[r0:r0 + 200_000])
            v = valid[r0:r0 + 200_000]
            bad += int((~np.isfinite(rows[v])).sum())
            if cols:
                guard_violations += int((rows[:, cols] != 0).sum())
        sv = np.asarray(stale[valid], dtype=np.float64)
        stale_ok = bool(np.isfinite(sv).all() and (sv >= 0).all())
        stats = json.loads(A.stdz_paths(cfg, set_name)[3].read_text(encoding="utf-8"))
        raw_guard_ok = True
        for ch in stats["guarded_raw_channels"]:
            b = np.memmap(A.braw_path(cfg, set_name, ch), mode="r", dtype=np.float32, shape=(nwin,))
            raw_guard_ok = raw_guard_ok and bool((np.asarray(b) == 0).all())
        finite_stats = bool(np.isfinite(meta["feat_mean"]).all() and np.isfinite(meta["feat_sd"]).all()
                            and (meta["feat_sd"] > 0).all())
        c = {"n_windows": nwin, "expected_windows": expect, "window_count_ok": nwin == expect,
             "nonfinite_in_valid_rows": bad, "finite_stats": finite_stats,
             "nominal_fit": stats["n_nominal_fit"], "nominal_val": stats["n_nominal_val"],
             "sup_pos": stats["n_sup_pos"], "sup_neg": stats["n_sup_neg"], "invalid_windows": int((~valid).sum()),
             "staleness_finite_nonnegative_on_valid": stale_ok, "stale_valid_windows": stats["stale_valid_windows"],
             "guarded_feature_columns": stats["guarded_feature_columns"], "guard_violations": guard_violations,
             "guarded_raw_channels": stats["guarded_raw_channels"], "raw_guard_ok": raw_guard_ok}
        c["pass"] = bool(c["window_count_ok"] and bad == 0 and finite_stats and c["nominal_fit"] > 0
                         and c["nominal_val"] > 0 and c["sup_pos"] > 0 and stale_ok and guard_violations == 0
                         and raw_guard_ok)
        ok = ok and c["pass"]
        checks[set_name] = c
    write(PT / "PT3_RESULT.json", {"test": "PT3_invariants", "protocol": "v3", "pass": ok, "sets": checks})
    return 0 if ok else 2


if __name__ == "__main__":
    which = sys.argv[1]
    sys.exit({"pt1": pt1, "pt2": pt2, "pt3": pt3}[which]())

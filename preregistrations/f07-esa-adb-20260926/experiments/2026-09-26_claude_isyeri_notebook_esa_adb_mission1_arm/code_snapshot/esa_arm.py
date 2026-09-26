"""Durable, label-isolated runner for the ESA-ADB Mission1 bounded arm (protocol v3).

Operation: f07-rb4-esa-adb-revision-20260926

Commands
  python esa_arm.py run [--only PREFIX] [--controlled-stop-after N] [--controlled-stop-marker PATH]
                        [--stop-before-fit]
  python esa_arm.py status
  python esa_arm.py plan

Each atomic unit writes its outputs atomically, then a checkpoint JSON with the SHA-256 of
every output. A rerun validates checkpoints and skips validated units (skipped_validated);
a unit whose outputs fail validation is quarantined and recomputed under a new attempt id.
A background thread writes heartbeat.json every 60 s and enforces the per-unit and whole-run
watchdogs. FREEZE GATE: a full-data fit unit refuses to start unless the verified public-freeze
record exists and names the exact SHA-256 of the executing code. Test-period labels are opened
only by the eval units. The scientific definitions are those of the frozen protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import esa_core as C  # noqa: E402

RUN_ID = "2026-09-26_claude_isyeri_notebook_esa_adb_mission1_arm"
RAW_ROOT = Path(os.environ.get("ESA_ADB_RAW_ROOT", "C:/ESA_ADB_RAW"))
CONTROLLED_EXIT = 75
TREE = ("dtree", "hgb", "iforest")
CLOSED_FORM = ("lr", "pca", "ae")
DEFAULT_TIMEOUTS_S = {"prep": 15 * 60, "stdz": 60 * 60, "fit": 90 * 60, "episodes": 60 * 60,
                      "attr_episode": 240 * 60, "eval": 240 * 60, "decision": 30 * 60}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def atomic_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(json.dumps(obj, indent=1, sort_keys=True, allow_nan=True, default=str).encode("utf-8"))
    os.replace(tmp, path)


def atomic_npy(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npy")
    np.save(tmp, arr, allow_pickle=False)
    os.replace(tmp, path)


def atomic_npz(path: Path, **arrays) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False)
    os.replace(tmp, path)


@dataclass
class Config:
    zip_path: Path
    meta_dir: Path
    work: Path
    run_dir: Path
    channel_sets: dict
    models: list
    grid_override: tuple | None = None  # (start_ns, end_ns) for property-test smoke runs
    n_fit: int = C.N_FIT
    n_bg: int = C.N_BG
    labels_csv: Path | None = None  # override for property tests (full table with test rows edited)
    per_unit_timeout_s: int = 90 * 60
    whole_run_timeout_s: int = 16 * 3600
    min_available_mb: int = 700
    min_free_disk_gb: float = 5.0
    reps: int = C.N_REP
    require_freeze: bool = True
    freeze_record: Path | None = None
    timeouts: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


def default_config() -> Config:
    # Path-only refactor after the pre-freeze evidence: the run folder is this file's parent folder and the raw
    # archive root comes from ESA_ADB_RAW_ROOT (default: the author host's location), so no machine-specific
    # project path is embedded. On the author host every resolved path is unchanged.
    run_dir = Path(__file__).resolve().parents[1]
    if run_dir.name != RUN_ID:
        raise RuntimeError(f"run folder {run_dir.name!r} is not {RUN_ID!r}")
    facts = json.loads((run_dir / "f3_schema/F3_FACTS.json").read_text(encoding="utf-8"))
    primary = list(facts["target_channels"])
    light = [f"channel_{i}" for i in range(41, 47)]
    timeouts = {}
    tpath = run_dir / "TIMEOUTS.json"
    if tpath.exists():
        timeouts = json.loads(tpath.read_text(encoding="utf-8-sig"))["timeouts_s"]
    return Config(zip_path=RAW_ROOT / "ESA-Mission1.zip", meta_dir=RAW_ROOT / "work" / "meta",
                  work=RAW_ROOT / "work" / "arm", run_dir=run_dir,
                  channel_sets={"primary": primary, "light": light}, models=list(C.MODELS),
                  freeze_record=run_dir / "freeze" / "PUBLIC_FREEZE_VERIFIED.json", timeouts=timeouts)


# ---------------------------------------------------------------- labels (the only label readers)
def read_segments(cfg: Config, pre_evaluation: bool) -> pd.DataFrame:
    types = C.load_meta_table(cfg.meta_dir, cfg.zip_path, "anomaly_types.csv")
    if cfg.labels_csv is not None:
        labels = pd.read_csv(cfg.labels_csv)
    else:
        labels = C.load_meta_table(cfg.meta_dir, cfg.zip_path, "labels.csv")
    segs = C.label_segments(labels, types)
    return C.pre_evaluation_segments(segs) if pre_evaluation else segs


# ---------------------------------------------------------------- runner infrastructure
def code_hashes() -> dict:
    return {p.name: sha256_file(p) for p in sorted(Path(__file__).resolve().parent.glob("esa_*.py"))}


class Runner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.units_dir = cfg.run_dir / "units"
        self.logs = cfg.run_dir / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.units_dir.mkdir(parents=True, exist_ok=True)
        cfg.work.mkdir(parents=True, exist_ok=True)
        self.current = {"unit_id": None, "attempt_id": None, "phase": "idle", "phase_started_at": None,
                        "unit_started_mono": None, "timeout_s": None}
        self.completed = 0
        self.planned = 0
        self.last_checkpoint_at = None
        self.started_mono = time.monotonic()
        self._stop = threading.Event()
        self.code_sha = code_hashes()

    # heartbeat and watchdogs
    def _heartbeat_loop(self):
        while not self._stop.wait(60):
            self.write_heartbeat()

    def write_heartbeat(self):
        cur = dict(self.current)
        elapsed = time.monotonic() - cur["unit_started_mono"] if cur["unit_started_mono"] else 0.0
        row = {"timestamp": now_iso(), "run_id": RUN_ID, "unit_id": cur["unit_id"], "attempt_id": cur["attempt_id"],
               "pid": os.getpid(), "phase": cur["phase"], "phase_started_at": cur["phase_started_at"],
               "unit_elapsed_seconds": round(elapsed, 1), "completed_atomic_units": self.completed,
               "planned_atomic_units": self.planned, "last_durable_checkpoint_at": self.last_checkpoint_at,
               "process_cpu_seconds": round(time.process_time(), 1),
               "run_elapsed_seconds": round(time.monotonic() - self.started_mono, 1)}
        try:
            import psutil

            row["rss_mb"] = round(psutil.Process().memory_info().rss / 2 ** 20, 1)
            row["available_mb"] = round(psutil.virtual_memory().available / 2 ** 20, 1)
        except Exception:  # pragma: no cover - observability only
            pass
        atomic_json(self.cfg.run_dir / "heartbeat.json", row)
        with (self.logs / "progress.jsonl").open("a", encoding="utf-8") as h:
            h.write(json.dumps(row) + "\n")
        limit = cur.get("timeout_s") or self.cfg.per_unit_timeout_s
        if cur["unit_started_mono"] and elapsed > limit:
            self.log_unit(unit=cur["unit_id"], attempt=cur["attempt_id"], status="timed_out", limit_s=limit)
            self.terminal("TIMED_OUT", 124, reason=f"unit {cur['unit_id']} exceeded {limit} s")
            os._exit(124)
        if time.monotonic() - self.started_mono > self.cfg.whole_run_timeout_s:
            self.terminal("TIMED_OUT", 124, reason="whole-run watchdog")
            os._exit(124)

    def phase(self, name: str):
        self.current["phase"] = name
        self.current["phase_started_at"] = now_iso()

    def log_unit(self, **row):
        row = {"at": now_iso(), **row}
        with (self.logs / "units.jsonl").open("a", encoding="utf-8") as h:
            h.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    def terminal(self, status: str, code: int, reason: str = ""):
        atomic_json(self.cfg.run_dir / "run_status.json",
                    {"status": status, "exit_code": code, "reason": reason, "at": now_iso(),
                     "completed_units": self.completed, "planned_units": self.planned, "run_id": RUN_ID})

    # checkpoints
    def ckpt_path(self, unit_id: str) -> Path:
        return self.units_dir / (unit_id.replace(":", "__") + ".json")

    def validated(self, unit_id: str) -> bool:
        p = self.ckpt_path(unit_id)
        if not p.exists():
            return False
        ck = json.loads(p.read_text(encoding="utf-8"))
        if ck.get("status") != "completed":
            return False
        for item in ck["outputs"]:
            fp = Path(item["path"])
            if not fp.exists() or fp.stat().st_size != item["bytes"] or sha256_file(fp) != item["sha256"]:
                return False
        return True

    def quarantine(self, unit_id: str, paths: list[Path]):
        q = self.cfg.work / "quarantine" / (unit_id.replace(":", "__") + "_" + uuid.uuid4().hex[:8])
        moved = []
        for p in paths:
            for cand in [p, p.with_name(p.name + ".tmp"), p.with_name(p.name + ".tmp.npy"), p.with_name(p.name + ".tmp.npz")]:
                if cand.exists():
                    q.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(cand), str(q / cand.name))
                    moved.append(str(cand))
        if moved:
            self.log_unit(unit=unit_id, status="quarantined_previous_outputs", moved=moved, to=str(q))

    def resources_ok(self, unit_id: str) -> None:
        import psutil

        waited = 0
        while True:
            avail = psutil.virtual_memory().available / 2 ** 20
            free = shutil.disk_usage(self.cfg.work).free / 2 ** 30
            if avail >= self.cfg.min_available_mb and free >= self.cfg.min_free_disk_gb:
                return
            if free < self.cfg.min_free_disk_gb or waited >= 1200:
                self.terminal("FAILED", 3, reason=f"resource ceiling before {unit_id}: available {avail:.0f} MB, free {free:.1f} GB")
                raise SystemExit(3)
            self.log_unit(unit=unit_id, status="waiting_for_memory", available_mb=round(avail), free_gb=round(free, 1))
            time.sleep(30)
            waited += 30

    def unit_timeout(self, unit_id: str) -> int:
        prefix = unit_id.split(":")[0]
        return int(self.cfg.timeouts.get(prefix) or DEFAULT_TIMEOUTS_S.get(prefix) or self.cfg.per_unit_timeout_s)

    def execute(self, unit_id: str, fn, outputs_fn):
        """Run one unit with checkpoint validation, quarantine and timing."""
        outputs = outputs_fn()
        if self.validated(unit_id):
            self.completed += 1
            self.log_unit(unit=unit_id, status="skipped_validated")
            return False
        self.quarantine(unit_id, outputs)
        self.resources_ok(unit_id)
        attempt = uuid.uuid4().hex[:12]
        self.current.update({"unit_id": unit_id, "attempt_id": attempt, "unit_started_mono": time.monotonic(),
                             "timeout_s": self.unit_timeout(unit_id)})
        self.phase("start")
        started = now_iso()
        self.log_unit(unit=unit_id, attempt=attempt, status="running")
        t0 = time.monotonic()
        try:
            extra = fn() or {}
        except Exception as exc:
            self.log_unit(unit=unit_id, attempt=attempt, status="failed", error=repr(exc), trace=traceback.format_exc()[-4000:])
            self.terminal("FAILED", 1, reason=f"{unit_id}: {exc!r}")
            raise
        missing = [str(p) for p in outputs if not p.exists()]
        if missing:
            self.terminal("FAILED", 1, reason=f"{unit_id}: missing outputs {missing}")
            raise RuntimeError(f"missing outputs {missing}")
        ck = {"unit_id": unit_id, "attempt_id": attempt, "status": "completed", "started_at": started,
              "ended_at": now_iso(), "elapsed_seconds": round(time.monotonic() - t0, 2),
              "outputs": [{"path": str(p), "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in outputs],
              "code_sha256": self.code_sha, "host": os.environ.get("COMPUTERNAME", ""), "extra": extra}
        atomic_json(self.ckpt_path(unit_id), ck)
        self.completed += 1
        self.last_checkpoint_at = ck["ended_at"]
        self.current.update({"unit_id": None, "attempt_id": None, "unit_started_mono": None, "timeout_s": None})
        self.phase("idle")
        self.log_unit(unit=unit_id, attempt=attempt, status="completed", elapsed_seconds=ck["elapsed_seconds"])
        return True


def assert_frozen(cfg: Config, runner: Runner) -> None:
    """Freeze gate: no full-data fit before the verified public freeze of this exact code."""
    if not cfg.require_freeze:
        return
    rec = cfg.freeze_record
    if rec is None or not rec.exists():
        raise RuntimeError("FREEZE_GATE: no verified public-freeze record; full-data fits are forbidden before the freeze")
    record = json.loads(rec.read_text(encoding="utf-8-sig"))
    if record.get("status") != "PUBLIC_FREEZE_VERIFIED":
        raise RuntimeError(f"FREEZE_GATE: freeze record status {record.get('status')!r}")
    if record.get("code_sha256") != runner.code_sha:
        raise RuntimeError("FREEZE_GATE: executing code differs from the frozen code snapshot")


# ---------------------------------------------------------------- geometry shared by units
def grid_geometry(cfg: Config) -> dict:
    path = cfg.work / "grid.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if cfg.grid_override is not None:
        start, end = cfg.grid_override
        n_grid = (end - start) // C.GRID_NS + 1
    else:
        facts = json.loads((cfg.run_dir / "f3_schema/F3_FACTS.json").read_text(encoding="utf-8"))
        samp = pd.read_csv(cfg.run_dir / "f3_schema/channel_sampling.csv")
        samp = samp[samp["channel"].isin(cfg.channel_sets["primary"])]
        first = [int(pd.Timestamp(x).value) for x in samp["first"]]
        last = [int(pd.Timestamp(x).value) for x in samp["last"]]
        start, end, n_grid = C.grid_bounds(first, last)
        assert len(samp) == facts["target_channel_count"]
    geo = {"grid_start_ns": int(start), "grid_end_ns": int(end), "n_grid": int(n_grid),
           "n_windows": int(C.n_windows(n_grid))}
    atomic_json(path, geo)
    return geo


# ---------------------------------------------------------------- unit: prep (label-free)
def prep_paths(cfg: Config, ch: str) -> list[Path]:
    d = cfg.work / "prep"
    return [d / f"{ch}.feat.f32", d / f"{ch}.valid.u1", d / f"{ch}.age.f32"]


def unit_prep(cfg: Config, runner: Runner, ch: str):
    geo = grid_geometry(cfg)
    runner.phase("load")
    t, v = C.load_channel_series(cfg.zip_path, ch)
    nwin = geo["n_windows"]
    paths = prep_paths(cfg, ch)
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    tmps = [p.with_name(p.name + ".tmp") for p in paths]
    feats = np.memmap(tmps[0], mode="w+", dtype=np.float32, shape=(nwin, C.NFEAT))
    valid = np.memmap(tmps[1], mode="w+", dtype=np.uint8, shape=(nwin,))
    ages = np.memmap(tmps[2], mode="w+", dtype=np.float32, shape=(nwin,))
    runner.phase("features")
    chunk = 200_000
    for k0 in range(0, nwin, chunk):
        k1 = min(nwin, k0 + chunk)
        g0 = k0 * C.STRIDE
        g1 = (k1 - 1) * C.STRIDE + C.W
        grid = geo["grid_start_ns"] + np.arange(g0, g1, dtype=np.int64) * C.GRID_NS
        x = C.zoh_values(t, v, grid)
        f, ok = C.window_features_chunk(x)
        f32 = f.astype(np.float32)
        if not np.isfinite(f32[ok]).all():
            raise RuntimeError(f"{ch}: valid-window features overflow float32")
        feats[k0:k1] = f32
        valid[k0:k1] = ok.astype(np.uint8)
        ages[k0:k1] = C.window_ages(t, geo["grid_start_ns"], k0, k1).astype(np.float32)
    feats.flush()
    valid.flush()
    ages.flush()
    del feats, valid, ages
    for tmp, final in zip(tmps, paths):
        os.replace(tmp, final)
    return {"n_samples": int(len(t)), "n_windows": nwin}


# ---------------------------------------------------------------- unit: stdz (pre-evaluation labels only)
def braw_path(cfg: Config, set_name: str, ch: str) -> Path:
    return cfg.work / set_name / "braw" / f"{ch}.f32"


def stdz_paths(cfg: Config, set_name: str) -> list[Path]:
    d = cfg.work / set_name
    return [d / "Z.f32", d / "stale.f32", d / "meta.npz", d / "stats.json"] + \
        [braw_path(cfg, set_name, ch) for ch in cfg.channel_sets[set_name]]


def unit_stdz(cfg: Config, runner: Runner, set_name: str):
    geo = grid_geometry(cfg)
    chans = cfg.channel_sets[set_name]
    nch = len(chans)
    nwin = geo["n_windows"]
    runner.phase("labels_pre_evaluation")
    segs = read_segments(cfg, pre_evaluation=True)
    assert (segs["S"] < C.TEST_START_NS).all()
    lo, hi = C.segment_window_ranges(segs["S"].to_numpy(), segs["E"].to_numpy(), geo["grid_start_ns"], nwin)
    labeled_any = C.mark_ranges(lo, hi, nwin)
    is_event = segs["Category"].isin(C.EVENT_CATEGORIES).to_numpy()
    is_gap = (segs["Category"] == C.GAP_CATEGORY).to_numpy()
    event_any = C.mark_ranges(lo[is_event], hi[is_event], nwin)
    gap_any = C.mark_ranges(lo[is_gap], hi[is_gap], nwin)
    runner.phase("validity_and_staleness")
    valid = np.ones(nwin, dtype=bool)
    stale = np.zeros(nwin, dtype=np.float64)
    for ch in chans:
        pp = prep_paths(cfg, ch)
        valid &= np.memmap(pp[1], mode="r", dtype=np.uint8, shape=(nwin,)).astype(bool)
        np.maximum(stale, np.asarray(np.memmap(pp[2], mode="r", dtype=np.float32, shape=(nwin,)), dtype=np.float64), out=stale)
    zpath, spath, metapath, statspath = stdz_paths(cfg, set_name)[:4]
    zpath.parent.mkdir(parents=True, exist_ok=True)
    tmps = spath.with_name(spath.name + ".tmp")
    sm = np.memmap(tmps, mode="w+", dtype=np.float32, shape=(nwin,))
    sm[:] = stale.astype(np.float32)
    sm.flush()
    del sm
    os.replace(tmps, spath)
    period = C.window_periods(geo["grid_start_ns"], nwin)
    nominal_fit = valid & (period == 0) & ~labeled_any
    nominal_val = valid & (period == 1) & ~labeled_any
    sup_y = np.full(nwin, -1, dtype=np.int8)
    fitv = valid & (period == 0)
    sup_y[fitv & nominal_fit] = 0
    sup_y[fitv & event_any] = 1
    assert nominal_fit.sum() > 0 and nominal_val.sum() > 0
    runner.phase("feature_stats")
    mean = np.zeros((C.NFEAT, nch))
    sd_pop = np.zeros((C.NFEAT, nch))
    for ci, ch in enumerate(chans):
        f = np.memmap(prep_paths(cfg, ch)[0], mode="r", dtype=np.float32, shape=(nwin, C.NFEAT))
        sel = np.asarray(f[nominal_fit], dtype=np.float64)
        mean[:, ci] = sel.mean(axis=0)
        sd_pop[:, ci] = sel.std(axis=0)
        del sel, f
    guard = C.guarded(sd_pop, mean)
    sd = sd_pop + 1e-9
    runner.phase("write_Z")
    tmpz = zpath.with_name(zpath.name + ".tmp")
    Z = np.memmap(tmpz, mode="w+", dtype=np.float32, shape=(nwin, C.NFEAT * nch))
    maps = [np.memmap(prep_paths(cfg, ch)[0], mode="r", dtype=np.float32, shape=(nwin, C.NFEAT)) for ch in chans]
    chunk = 100_000
    for r0 in range(0, nwin, chunk):
        r1 = min(nwin, r0 + chunk)
        block = np.empty((r1 - r0, C.NFEAT * nch), dtype=np.float64)
        for ci in range(nch):
            raw = np.asarray(maps[ci][r0:r1], dtype=np.float64)
            for fi in range(C.NFEAT):
                if guard[fi, ci]:
                    block[:, fi * nch + ci] = 0.0
                else:
                    block[:, fi * nch + ci] = (raw[:, fi] - mean[fi, ci]) / sd[fi, ci]
        Z[r0:r1] = block.astype(np.float32)
    Z.flush()
    del Z, maps
    os.replace(tmpz, zpath)
    runner.phase("raw_deviation")
    raw_stats = {}
    guarded_raw = []
    glab = C.grid_labeled_mask(segs["S"].to_numpy(), segs["E"].to_numpy(), geo["grid_start_ns"], geo["n_grid"])
    gtimes_fit_end = (C.VAL_START_NS - geo["grid_start_ns"]) // C.GRID_NS  # grid indices < this are fit period
    for ch in chans:
        bp = braw_path(cfg, set_name, ch)
        t, v = C.load_channel_series(cfg.zip_path, ch)
        x = np.empty(geo["n_grid"], dtype=np.float64)
        gstep = 1_000_000
        for g0 in range(0, geo["n_grid"], gstep):
            g1 = min(geo["n_grid"], g0 + gstep)
            grid = geo["grid_start_ns"] + np.arange(g0, g1, dtype=np.int64) * C.GRID_NS
            x[g0:g1] = C.zoh_values(t, v, grid)
        del t, v
        fitmask = np.zeros(geo["n_grid"], dtype=bool)
        fitmask[: max(0, min(geo["n_grid"], gtimes_fit_end))] = True
        use = fitmask & ~glab & np.isfinite(x)
        mu = float(x[use].mean())
        sdv = float(x[use].std())
        g = bool(C.guarded(np.asarray([sdv]), np.asarray([mu]))[0])
        raw_stats[ch] = {"mu": mu, "sd": sdv, "n": int(use.sum()), "guarded": g}
        if g:
            guarded_raw.append(ch)
        bp.parent.mkdir(parents=True, exist_ok=True)
        tmpb = bp.with_name(bp.name + ".tmp")
        out = np.memmap(tmpb, mode="w+", dtype=np.float32, shape=(nwin,))
        step = 200_000
        for k0 in range(0, nwin, step):
            k1 = min(nwin, k0 + step)
            if g:
                out[k0:k1] = 0.0
                continue
            g0 = k0 * C.STRIDE
            g1 = (k1 - 1) * C.STRIDE + C.W
            out[k0:k1] = C.window_mean_abs_z(x[g0:g1], mu, sdv).astype(np.float32)
        out.flush()
        del out
        os.replace(tmpb, bp)
        del x, use, fitmask
    runner.phase("background")
    fit_idx = np.flatnonzero(nominal_fit)
    rng = np.random.default_rng(C.BG_SEED)
    bg_idx = np.sort(rng.choice(fit_idx, size=min(cfg.n_bg, len(fit_idx)), replace=False))
    val_idx = np.flatnonzero(valid & (period == 1))
    test_idx = np.flatnonzero(valid & (period == 2))
    atomic_npz(metapath, valid=valid, period=period, labeled_any_pre=labeled_any, event_any_pre=event_any,
               gap_any_pre=gap_any, nominal_fit=nominal_fit, nominal_val=nominal_val, sup_y=sup_y, bg_idx=bg_idx,
               val_idx=val_idx, test_idx=test_idx, feat_mean=mean, feat_sd=sd, feat_guard=guard)
    guarded_cols = [{"channel": chans[ci], "feature": ["mean", "sd", "slope", "delta"][fi]}
                    for fi in range(C.NFEAT) for ci in range(nch) if guard[fi, ci]]
    stale_valid = stale[valid]
    stats = {"set": set_name, "channels": chans, "n_windows": nwin, "n_valid": int(valid.sum()),
             "n_nominal_fit": int(nominal_fit.sum()), "n_nominal_val": int(nominal_val.sum()),
             "n_sup_pos": int((sup_y == 1).sum()), "n_sup_neg": int((sup_y == 0).sum()),
             "n_val_valid": int(len(val_idx)), "n_test_valid": int(len(test_idx)),
             "n_boundary": int((period == 3).sum()), "raw_stats": raw_stats,
             "guarded_feature_columns": guarded_cols,
             "guarded_feature_channels": sorted({c["channel"] for c in guarded_cols}),
             "guarded_raw_channels": guarded_raw,
             "stale_valid_windows": int((stale_valid > C.STALE_S).sum()),
             "pre_evaluation_segments": int(len(segs)),
             "braw_sha256": {ch: sha256_file(braw_path(cfg, set_name, ch)) for ch in chans}}
    atomic_json(statspath, stats)
    return {k: stats[k] for k in ("n_valid", "n_nominal_fit", "n_nominal_val", "n_sup_pos", "n_sup_neg",
                                  "n_test_valid", "guarded_feature_channels", "guarded_raw_channels")}


def load_set(cfg: Config, set_name: str):
    geo = grid_geometry(cfg)
    nch = len(cfg.channel_sets[set_name])
    zpath, spath, metapath, _ = stdz_paths(cfg, set_name)[:4]
    Z = np.memmap(zpath, mode="r", dtype=np.float32, shape=(geo["n_windows"], C.NFEAT * nch))
    stale = np.memmap(spath, mode="r", dtype=np.float32, shape=(geo["n_windows"],))
    meta = dict(np.load(metapath))
    return geo, Z, meta, stale


def load_stats(cfg: Config, set_name: str) -> dict:
    return json.loads(stdz_paths(cfg, set_name)[3].read_text(encoding="utf-8"))


def gather(Z: np.memmap, idx: np.ndarray) -> np.ndarray:
    idx = np.asarray(idx, dtype=np.int64)
    order = np.argsort(idx, kind="stable")
    rows = np.asarray(Z[idx[order]], dtype=np.float64)
    out = np.empty_like(rows)
    out[order] = rows
    return out


def braw_maps(cfg: Config, set_name: str, nwin: int) -> list:
    return [np.memmap(braw_path(cfg, set_name, c), mode="r", dtype=np.float32, shape=(nwin,))
            for c in cfg.channel_sets[set_name]]


def braw_rows(maps: list, windows: np.ndarray) -> np.ndarray:
    windows = np.asarray(windows, dtype=np.int64)
    if len(windows) == 0:
        return np.zeros((0, len(maps)))
    return np.stack([np.asarray(m[windows], dtype=np.float64) for m in maps], axis=1)


# ---------------------------------------------------------------- unit: fit + scores
def fit_paths(cfg: Config, set_name: str, model: str, rep: int) -> list[Path]:
    d = cfg.work / set_name / "fits"
    ext = "pt" if model == "ae" else "joblib"
    return [d / f"{model}_r{rep}.{ext}", d / f"{model}_r{rep}.val.npy", d / f"{model}_r{rep}.test.npy"]


def save_model(model_name: str, model, path: Path):
    tmp = path.with_name(path.name + ".tmp")
    if model_name == "ae":
        import torch

        torch.save(model.net.state_dict(), tmp)
    else:
        import joblib

        joblib.dump(model, tmp)
    os.replace(tmp, path)


def load_model(model_name: str, path: Path, d: int, rep: int):
    if model_name == "ae":
        import torch

        ae = C.AE(d, rep)
        ae.net.load_state_dict(torch.load(path, weights_only=True))
        ae.net.eval()
        return ae
    import joblib

    return joblib.load(path)


def score_rows(model_name: str, model, Z: np.memmap, idx: np.ndarray, chunk: int = 50_000) -> np.ndarray:
    out = np.empty(len(idx), dtype=np.float64)
    for i in range(0, len(idx), chunk):
        rows = np.asarray(Z[idx[i:i + chunk]], dtype=np.float64)
        out[i:i + chunk] = C.score(model_name, model, rows)
    if not np.isfinite(out).all():
        raise RuntimeError("non-finite scores")
    return out


def unit_fit(cfg: Config, runner: Runner, set_name: str, model_name: str, rep: int):
    assert_frozen(cfg, runner)
    geo, Z, meta, _ = load_set(cfg, set_name)
    rng = np.random.default_rng(1000 * rep + 7)
    if C.SUPERVISED[model_name]:
        eligible = np.flatnonzero(meta["sup_y"] >= 0)
    else:
        eligible = np.flatnonzero(meta["nominal_fit"])
    idx = eligible[rng.choice(len(eligible), cfg.n_fit, replace=True)]
    runner.phase("gather")
    X = gather(Z, idx)
    y = meta["sup_y"][idx].astype(int) if C.SUPERVISED[model_name] else None
    if y is not None and len(np.unique(y)) < 2:
        raise RuntimeError("bootstrap sample lacks both classes")
    runner.phase("fit")
    t0 = time.monotonic()
    model = C.build_and_fit(model_name, rep, X, y)
    fit_s = time.monotonic() - t0
    del X
    mpath, vpath, tpath = fit_paths(cfg, set_name, model_name, rep)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    save_model(model_name, model, mpath)
    runner.phase("score_validation")
    atomic_npy(vpath, score_rows(model_name, model, Z, meta["val_idx"]))
    runner.phase("score_test")
    t1 = time.monotonic()
    atomic_npy(tpath, score_rows(model_name, model, Z, meta["test_idx"]))
    extra = {"fit_seconds": round(fit_s, 2), "score_test_seconds": round(time.monotonic() - t1, 2),
             "n_fit": int(cfg.n_fit), "positives": int(y.sum()) if y is not None else None}
    if model_name == "pca":
        extra["pca_fit_svd_solver"] = str(getattr(model, "_fit_svd_solver", model.svd_solver))
    return extra


# ---------------------------------------------------------------- unit: episodes (+ raw/feature masses)
def episode_paths(cfg: Config, set_name: str, model: str) -> list[Path]:
    return [cfg.work / set_name / "episodes" / f"{model}.npz"]


def episode_runs(flags: np.ndarray, test_idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    starts, ends = [], []
    i = 0
    n = len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j + 1 < n and flags[j + 1] and test_idx[j + 1] == test_idx[j] + 1:
                j += 1
            starts.append(i)
            ends.append(j)
            i = j + 1
        else:
            i += 1
    return np.asarray(starts, dtype=np.int64), np.asarray(ends, dtype=np.int64)


def flagged_layout(starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lengths = ends - starts + 1
    ep_of_flag = np.repeat(np.arange(len(starts), dtype=np.int64), lengths)
    flag_pos = np.concatenate([np.arange(a, b + 1, dtype=np.int64) for a, b in zip(starts, ends)]) \
        if len(starts) else np.zeros(0, dtype=np.int64)
    return flag_pos, ep_of_flag


def unit_episodes(cfg: Config, runner: Runner, set_name: str, model_name: str):
    geo, Z, meta, stale = load_set(cfg, set_name)
    nch = len(cfg.channel_sets[set_name])
    val = np.mean([np.load(fit_paths(cfg, set_name, model_name, r)[1]) for r in range(cfg.reps)], axis=0)
    test = np.mean([np.load(fit_paths(cfg, set_name, model_name, r)[2]) for r in range(cfg.reps)], axis=0)
    val_idx, test_idx = meta["val_idx"], meta["test_idx"]
    ref = val[meta["nominal_val"][val_idx]]
    thr = float(np.quantile(ref, 0.99))
    flags = test > thr
    starts, ends = episode_runs(flags, test_idx)
    n_ep = len(starts)
    peaks = np.asarray([a + int(np.argmax(test[a:b + 1])) for a, b in zip(starts, ends)], dtype=np.int64)
    tau = C.tail_surprisal(test[peaks], ref) if n_ep else np.zeros(0)
    flag_pos, ep_of_flag = flagged_layout(starts, ends)
    if not np.array_equal(flag_pos, np.flatnonzero(flags)):
        raise RuntimeError("episode layout does not cover the flagged windows exactly")
    weights = C.tail_surprisal(test[flag_pos], ref) if len(flag_pos) else np.zeros(0)
    flag_win = test_idx[flag_pos]
    peak_win = test_idx[peaks] if n_ep else np.zeros(0, dtype=np.int64)
    maps = braw_maps(cfg, set_name, geo["n_windows"])
    runner.phase("aggregated_raw_feature")
    agg_raw = C.EpisodeAggregator(ep_of_flag, weights, n_ep, nch)
    agg_feat = C.EpisodeAggregator(ep_of_flag, weights, n_ep, nch)
    for i0 in range(0, len(flag_pos), 50_000):
        i1 = min(len(flag_pos), i0 + 50_000)
        w = flag_win[i0:i1]
        agg_raw.add(i0, i1, braw_rows(maps, w))
        agg_feat.add(i0, i1, C.feature_mass(gather(Z, w), nch))
    ar, ar_rd, ar_wd = agg_raw.result()
    af, af_rd, af_wd = agg_feat.result()
    runner.phase("peak_raw_feature")
    peak_raw, peak_raw_deg = C.normalise_mass(braw_rows(maps, peak_win)) if n_ep else (np.zeros((0, nch)), np.zeros(0, bool))
    peak_feat, peak_feat_deg = C.normalise_mass(C.feature_mass(gather(Z, peak_win), nch)) if n_ep else (np.zeros((0, nch)), np.zeros(0, bool))
    peak_staleness = np.asarray(stale[peak_win], dtype=np.float64) if n_ep else np.zeros(0)
    atomic_npz(episode_paths(cfg, set_name, model_name)[0], threshold=np.asarray([thr]), flags=flags,
               ep_start=starts, ep_end=ends, ep_peak=peaks, ep_peak_window=peak_win, tau=tau,
               mean_test=test, mean_val=val, nominal_val_ref=ref, flag_pos=flag_pos, window_weight=weights,
               peak_raw=peak_raw, peak_raw_deg=peak_raw_deg, peak_feature=peak_feat, peak_feature_deg=peak_feat_deg,
               agg_raw=ar, agg_raw_deg=ar_rd | ar_wd, agg_feature=af, agg_feature_deg=af_rd | af_wd,
               peak_staleness_s=peak_staleness)
    return {"threshold": thr, "n_flagged": int(flags.sum()), "n_episodes": int(n_ep),
            "flag_rate": round(float(flags.mean()), 6)}


# ---------------------------------------------------------------- unit: episode attributions
def attr_paths(cfg: Config, set_name: str, model: str, rep: int) -> list[Path]:
    return [cfg.work / set_name / "attr" / f"episode_{model}_r{rep}.npz"]


def attr_context(cfg: Config, set_name: str, model_name: str, rep: int, offset: int) -> dict:
    geo, Z, meta, _ = load_set(cfg, set_name)
    nch = len(cfg.channel_sets[set_name])
    model = load_model(model_name, fit_paths(cfg, set_name, model_name, rep)[0], C.NFEAT * nch, rep)
    background = gather(Z, meta["bg_idx"])
    bg_mean = background.mean(axis=0)
    draws = C.occlusion_draws(background, offset, rep)
    del background
    return {"Z": Z, "meta": meta, "nch": nch, "model": model, "name": model_name, "bg_mean": bg_mean,
            "draws": draws, "explainer": C.tree_explainer(model_name, model)}


def attr_rows(ctx: dict, windows: np.ndarray, native: bool, occlusion: bool, runner: Runner | None = None,
              label: str = "attr") -> tuple[np.ndarray, np.ndarray]:
    n = len(windows)
    nat = np.full((n, ctx["nch"]), np.nan)
    occ = np.full((n, ctx["nch"]), np.nan)
    batch = 400
    for i in range(0, n, batch):
        if runner is not None:
            runner.phase(f"{label}_batch_{i // batch}")
        Zq = gather(ctx["Z"], windows[i:i + batch])
        if native:
            nat[i:i + batch] = C.native_attr(ctx["name"], ctx["model"], Zq, ctx["bg_mean"], ctx["nch"], ctx["explainer"])
        if occlusion:
            occ[i:i + batch] = C.occlusion_attr(ctx["name"], ctx["model"], Zq, ctx["draws"], ctx["nch"])
    return nat, occ


def episode_subsample(n_ep: int, model_name: str) -> tuple[np.ndarray, bool]:
    if n_ep > C.CAP_EPISODES:
        mi = C.MODELS.index(model_name)
        return np.sort(np.random.default_rng(20260926 + mi).choice(n_ep, C.CAP_EPISODES, replace=False)), True
    return np.arange(n_ep, dtype=np.int64), False


def unit_attr_episode(cfg: Config, runner: Runner, set_name: str, model_name: str, rep: int):
    ep = np.load(episode_paths(cfg, set_name, model_name)[0])
    q = ep["ep_peak_window"]
    n_ep = len(q)
    sub, capped = episode_subsample(n_ep, model_name)
    ctx = attr_context(cfg, set_name, model_name, rep, C.EPISODE_QUERY_OFFSET)
    nch = ctx["nch"]
    nat = np.full((n_ep, nch), np.nan)
    occ = np.full((n_ep, nch), np.nan)
    native_rows = sub if model_name in TREE else np.arange(n_ep, dtype=np.int64)
    if len(native_rows):
        nat[native_rows] = attr_rows(ctx, q[native_rows], True, False, runner, "peak_native")[0]
    if len(sub):
        occ[sub] = attr_rows(ctx, q[sub], False, True, runner, "peak_occlusion")[1]
    agg = {"native_agg": np.zeros((0, nch)), "native_agg_rep_deg": np.zeros(0, bool), "native_agg_win_deg": np.zeros(0, bool)}
    if model_name in CLOSED_FORM and n_ep:
        flag_pos, ep_of_flag = flagged_layout(ep["ep_start"], ep["ep_end"])
        flag_win = ctx["meta"]["test_idx"][flag_pos]
        aggr = C.EpisodeAggregator(ep_of_flag, ep["window_weight"], n_ep, nch)
        for i0 in range(0, len(flag_pos), 50_000):
            runner.phase(f"aggregated_native_{i0 // 50_000}")
            i1 = min(len(flag_pos), i0 + 50_000)
            Zq = gather(ctx["Z"], flag_win[i0:i1])
            aggr.add(i0, i1, C.native_attr(model_name, ctx["model"], Zq, ctx["bg_mean"], nch, ctx["explainer"]))
        m, rd, wd = aggr.result()
        agg = {"native_agg": m, "native_agg_rep_deg": rd, "native_agg_win_deg": wd}
    atomic_npz(attr_paths(cfg, set_name, model_name, rep)[0], native=nat, occlusion=occ, subsample=sub,
               capped=np.asarray([capped]), native_rows=native_rows, query_windows=q, **agg)
    return {"n_episodes": int(n_ep), "capped": bool(capped), "n_model_call_rows": int(len(sub))}


# ---------------------------------------------------------------- eval helpers
def queue_muc(values: np.ndarray, seed: int, ep_ids: list, n_ev: int) -> float:
    if len(values) == 0:
        return 0.0
    orders = C.tie_orderings(values, seed)
    return float(np.mean([C.muc_auc_equal(o, ep_ids, n_ev) for o in orders]))


def e2_stats(M: np.ndarray, chans: list) -> dict:
    ent = np.asarray([C.normalized_entropy(r) for r in M])
    tops = np.argmax(M, axis=1)
    counts = np.bincount(tops, minlength=len(chans))
    top3 = np.argsort(-counts, kind="stable")[:3]
    return {"n": int(len(M)), "mean_entropy": float(ent.mean()), "dominant_channel": chans[int(np.argmax(counts))],
            "dominant_share": float(counts.max() / len(M)), "top3_share": float(counts[top3].sum() / len(M))}


def e3_block(M: np.ndarray, tau: np.ndarray, is_fa: np.ndarray, ep_ids: list, n_ev: int, mi: int,
             chans: list) -> tuple[list, dict]:
    nch = len(chans)
    order0 = C.tie_orderings(tau, 20260926 + 1000 * mi + 999)
    base_fa = {f: float(np.mean([C.fa_share_at(o, is_fa)[f] for o in order0])) for f in C.FRACTIONS}
    muc0 = float(np.mean([C.muc_auc_equal(o, ep_ids, n_ev) for o in order0]))
    fa_counts = np.bincount(np.argmax(M[is_fa], axis=1), minlength=nch) if is_fa.any() else np.zeros(nch)
    fa_top_freq = fa_counts / max(1, int(is_fa.sum()))
    rows, deltas10, dmuc = [], [], []
    for k in range(nch):
        prof = np.ones(nch)
        prof[k] = 4.0
        pri = tau * ((M @ prof) / prof.mean())
        orders = C.tie_orderings(pri, 20260926 + 1000 * mi + k)
        fa = {f: float(np.mean([C.fa_share_at(o, is_fa)[f] for o in orders])) for f in C.FRACTIONS}
        muc = float(np.mean([C.muc_auc_equal(o, ep_ids, n_ev) for o in orders]))
        row = {"channel": chans[k], "fa_top_frequency": float(fa_top_freq[k]), "delta_muc": muc - muc0,
               **{f"delta_fa_{int(round(f * 100))}": fa[f] - base_fa[f] for f in C.FRACTIONS}}
        rows.append(row)
        deltas10.append(row["delta_fa_10"])
        dmuc.append(row["delta_muc"])
    from scipy.stats import spearmanr

    rho = spearmanr(fa_top_freq, deltas10).statistic if np.ptp(fa_top_freq) > 0 and np.ptp(deltas10) > 0 else float("nan")
    summary = {"n_episodes": int(len(tau)), "n_fa": int(is_fa.sum()), "n_events": int(n_ev), "muc_score_only": muc0,
               "base_fa_10": base_fa[0.10], "spearman_fa_top_freq_vs_delta_fa_10": float(rho),
               "max_delta_fa_10": float(np.max(deltas10)), "median_delta_fa_10": float(np.median(deltas10)),
               "channel_of_max_delta_fa_10": chans[int(np.argmax(deltas10))],
               "min_delta_muc": float(np.min(dmuc)), "median_delta_muc": float(np.median(dmuc))}
    return rows, summary


def remap_events(ep_ids: list, keep_events: np.ndarray) -> tuple[list, int]:
    new_index = {int(e): i for i, e in enumerate(np.flatnonzero(keep_events))}
    return [[new_index[x] for x in ids if x in new_index] for ids in ep_ids], len(new_index)


def mass_summary_rows(e1: pd.DataFrame) -> pd.DataFrame:
    if not len(e1):
        return pd.DataFrame(columns=["stratum", "model", "source", "n"])
    parts = []
    strata = [("all", e1), ("pre_drift", e1[e1["subperiod"] == "pre_drift"]), ("drift", e1[e1["subperiod"] == "drift"]),
              ("anomalies_only", e1[e1["category"] == "Anomaly"])]
    for name, df in strata:
        if not len(df):
            continue
        g = df.groupby(["model", "source"])
        s = g.agg(n=("event", "nunique"), auroc=("auroc", "mean"), hit1=("hit1", "mean"), hit3=("hit3", "mean"),
                  best_rank=("best_rank", "mean"), r_precision=("r_precision", "mean"),
                  chance_hit1=("chance_hit1", "mean"), chance_hit3=("chance_hit3", "mean"),
                  chance_rprec=("chance_rprec", "mean"), stale_peak_share=("peak_stale", "mean")).reset_index()
        s["n_auroc"] = g["auroc"].apply(lambda x: int(x.notna().sum())).to_numpy()
        s.insert(0, "stratum", name)
        parts.append(s)
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------- unit: eval (first reader of test labels)
def eval_paths(cfg: Config, set_name: str) -> list[Path]:
    d = cfg.run_dir / "results" / set_name
    base = [d / "E1_event_rows.csv", d / "E1_summary.csv", d / "E4_detection.csv", d / "E4_year_context.csv",
            d / "E4_subperiod.csv", d / "E2_summary.csv", d / "episode_rows.csv", d / "EVAL_SUMMARY.json"]
    if set_name == "primary":
        base += [d / "E3_channel_rows.csv", d / "E3_summary.csv"]
    base += [cfg.work / set_name / "eval" / f"event_masses_{m}.npz" for m in cfg.models]
    return base


def unit_eval(cfg: Config, runner: Runner, set_name: str):
    from sklearn.metrics import average_precision_score, roc_auc_score

    geo, Z, meta, stale = load_set(cfg, set_name)
    stats = load_stats(cfg, set_name)
    guarded_ch = set(stats["guarded_feature_channels"]) | set(stats["guarded_raw_channels"])
    chans = cfg.channel_sets[set_name]
    nch = len(chans)
    ch_index = {c: i for i, c in enumerate(chans)}
    nwin = geo["n_windows"]
    runner.phase("open_test_labels")
    segs = read_segments(cfg, pre_evaluation=False)
    types = C.load_meta_table(cfg.meta_dir, cfg.zip_path, "anomaly_types.csv")
    cls_of = dict(zip(types["ID"].astype(str), types["Class"].astype(str)))
    test_idx = meta["test_idx"]
    ntest = len(test_idx)
    pos_in_test = np.full(nwin, -1, dtype=np.int64)
    pos_in_test[test_idx] = np.arange(ntest)
    ws_test = C.window_start_ns(geo["grid_start_ns"], test_idx)
    lo, hi = C.segment_window_ranges(segs["S"].to_numpy(), segs["E"].to_numpy(), geo["grid_start_ns"], nwin)
    segs = segs.assign(lo=lo, hi=hi)
    test_segs = segs[segs["S"] >= C.TEST_START_NS]
    ev_segs = test_segs[test_segs["Category"].isin(C.EVENT_CATEGORIES)]
    events = []
    for eid, g in ev_segs.groupby("ID", sort=True):
        affected = np.zeros(nch, dtype=bool)
        for c in g["Channel"]:
            if c in ch_index:
                affected[ch_index[c]] = True
        rng_w = [np.arange(a, b + 1) for a, b in zip(g["lo"], g["hi"]) if b >= a]
        wins = np.unique(np.concatenate(rng_w)) if rng_w else np.zeros(0, dtype=np.int64)
        wins = wins[(wins >= 0) & (wins < nwin)]
        tpos = pos_in_test[wins]
        tpos = np.sort(tpos[tpos >= 0])
        s0 = int(g["S"].min())
        events.append({"id": str(eid), "category": g["Category"].iloc[0], "class": cls_of.get(str(eid), "NA"),
                       "affected": affected, "m": int(affected.sum()), "test_pos": tpos,
                       "segments": [(int(a), int(b)) for a, b in zip(g["S"], g["E"])], "start_ns": s0,
                       "end_ns": int(g["E"].max()), "subperiod": "drift" if s0 >= C.DRIFT_START_NS else "pre_drift"})
    scoreable = [e for e in events if e["m"] > 0]
    n_events = len(scoreable)
    ev_drift = np.asarray([e["subperiod"] == "drift" for e in scoreable], dtype=bool)
    include_all = np.ones(n_events, dtype=bool)
    include_anom = np.asarray([e["category"] == "Anomaly" for e in scoreable], dtype=bool)

    def mark(frame: pd.DataFrame) -> np.ndarray:
        out = np.zeros(ntest, dtype=bool)
        for a, b in zip(frame["lo"], frame["hi"]):
            w = np.arange(max(0, int(a)), min(nwin - 1, int(b)) + 1)
            p = pos_in_test[w]
            out[p[p >= 0]] = True
        return out

    labeled_test = mark(test_segs)
    gap_mask_test = mark(test_segs[test_segs["Category"] == C.GAP_CATEGORY])
    nominal_test = ~labeled_test
    event_window_label = np.zeros(ntest, dtype=bool)
    for e in scoreable:
        event_window_label[e["test_pos"]] = True
    stale_test = np.asarray(stale[test_idx], dtype=np.float64) > C.STALE_S
    test_drift = ws_test >= C.DRIFT_START_NS
    test_year = ws_test.astype("datetime64[ns]").astype("datetime64[Y]").astype(int) + 1970
    all_ev_s = ev_segs["S"].to_numpy(dtype=np.int64)
    all_ev_e = ev_segs["E"].to_numpy(dtype=np.int64)
    t0, t1 = C.TEST_START_NS, int(geo["grid_end_ns"])
    win_to_events: dict[int, list[int]] = {}
    for ei, e in enumerate(scoreable):
        for tp in e["test_pos"]:
            win_to_events.setdefault(int(tp), []).append(ei)
    overlap_pairs = sum(1 for i in range(len(events)) for j in range(i + 1, len(events))
                        if events[i]["start_ns"] <= events[j]["end_ns"] and events[j]["start_ns"] <= events[i]["end_ns"])
    maps = braw_maps(cfg, set_name, nwin)
    e1_rows, det_rows, year_rows, sub_rows, ep_frames, e2_rows, e3_rows, e3_summary = [], [], [], [], [], [], [], []
    for model_name in cfg.models:
        mi = C.MODELS.index(model_name)
        runner.phase(f"eval_{model_name}")
        ep = np.load(episode_paths(cfg, set_name, model_name)[0])
        flags, mean_test = ep["flags"], ep["mean_test"]
        detected, peaks = [], []
        for e in scoreable:
            tp = e["test_pos"]
            det = bool(len(tp)) and bool(flags[tp].any())
            detected.append(det)
            peaks.append(int(tp[int(np.argmax(mean_test[tp]))]) if det else -1)
        det_events = [(e, p) for e, p, d in zip(scoreable, peaks, detected) if d]
        mass_store = {"event_ids": np.asarray([e["id"] for e, _ in det_events], dtype=str),
                      "peak_windows": np.asarray([int(test_idx[p]) for _, p in det_events], dtype=np.int64)}
        if det_events:
            qwin = test_idx[np.asarray([p for _, p in det_events], dtype=np.int64)]
            reps_nat, reps_occ = [], []
            for rep in range(cfg.reps):
                ctx = attr_context(cfg, set_name, model_name, rep, C.EVENT_QUERY_OFFSET)
                nat, occ = attr_rows(ctx, qwin, True, True)
                reps_nat.append(nat)
                reps_occ.append(occ)
                del ctx
            masses = {"native": C.mean_mass(np.asarray(reps_nat))[0], "occlusion": C.mean_mass(np.asarray(reps_occ))[0],
                      "raw": C.normalise_mass(braw_rows(maps, qwin))[0],
                      "feature": C.normalise_mass(C.feature_mass(gather(Z, qwin), nch))[0]}
            mass_store.update({f"mass_{k}": v for k, v in masses.items()})
            mass_store["native_replicates"] = np.asarray(reps_nat)
            mass_store["occlusion_replicates"] = np.asarray(reps_occ)
            peak_stale = np.asarray(stale[qwin], dtype=np.float64) > C.STALE_S
            for j, (e, p) in enumerate(det_events):
                for src, M in masses.items():
                    mass = M[j]
                    top = chans[int(np.argmax(mass))]
                    e1_rows.append({"set": set_name, "model": model_name, "event": e["id"], "category": e["category"],
                                    "class": e["class"], "subperiod": e["subperiod"], "m": e["m"], "C": nch, "source": src,
                                    "auroc": C.ranking_auroc(mass, e["affected"]),
                                    "hit1": C.hit_at_k(mass, e["affected"], 1), "hit3": C.hit_at_k(mass, e["affected"], 3),
                                    "best_rank": C.best_affected_rank(mass, e["affected"]),
                                    "r_precision": C.r_precision(mass, e["affected"]),
                                    "chance_hit1": C.hit_chance(nch, e["m"], 1), "chance_hit3": C.hit_chance(nch, e["m"], 3),
                                    "chance_rprec": e["m"] / nch, "peak_window": int(test_idx[p]),
                                    "peak_stale": bool(peak_stale[j]), "top_channel": top, "top_guarded": top in guarded_ch})
        atomic_npz(cfg.work / set_name / "eval" / f"event_masses_{model_name}.npz", **mass_store)
        # episodes: classification and event ids
        ep_start, ep_end = ep["ep_start"], ep["ep_end"]
        n_ep = len(ep_start)
        ep_event_ids, is_fa, is_ta, is_other = [], np.zeros(n_ep, bool), np.zeros(n_ep, bool), np.zeros(n_ep, bool)
        for k in range(n_ep):
            a, b = int(ep_start[k]), int(ep_end[k])
            ids = sorted({x for tp in range(a, b + 1) for x in win_to_events.get(tp, [])})
            ep_event_ids.append(ids)
            lab = bool(labeled_test[a:b + 1].any())
            is_ta[k] = bool(ids)
            is_fa[k] = not lab
            is_other[k] = lab and not ids
        n_multi = np.asarray([len(x) > 1 for x in ep_event_ids], dtype=bool)
        ep_drift = ws_test[ep_start] >= C.DRIFT_START_NS if n_ep else np.zeros(0, bool)
        ep_year = test_year[ep_start] if n_ep else np.zeros(0, int)
        ep_len = ep_end - ep_start + 1
        ep_stale = ep["peak_staleness_s"] > C.STALE_S
        tau = ep["tau"] + 1e-12
        n_det = int(np.sum(detected))
        muc_score = queue_muc(tau, 20260926 + 1000 * mi + 999, ep_event_ids, n_events)
        yw = event_window_label[~gap_mask_test | event_window_label]
        sw = mean_test[~gap_mask_test | event_window_label]
        p_nom = float(flags[nominal_test].mean()) if nominal_test.any() else float("nan")
        alarm_s = ws_test[ep_start] if n_ep else np.zeros(0, np.int64)
        alarm_e = ws_test[ep_end] + C.WINDOW_SPAN_NS if n_ep else np.zeros(0, np.int64)
        seg_lists = [e["segments"] for e in scoreable]
        vor_all = C.vor_corrected_event_wise(alarm_s, alarm_e, seg_lists, include_all, all_ev_s, all_ev_e, t0, t1)
        vor_anom = C.vor_corrected_event_wise(alarm_s, alarm_e, seg_lists, include_anom, all_ev_s, all_ev_e, t0, t1)
        keep = ~ep_stale
        ids_keep = [ep_event_ids[k] for k in np.flatnonzero(keep)]
        attr_capped = []
        for rep in range(cfg.reps):
            ap = attr_paths(cfg, set_name, model_name, rep)[0]
            attr_capped.append(bool(np.load(ap)["capped"][0]) if ap.exists() else None)
        det_rows.append({"set": set_name, "model": model_name, "threshold": float(ep["threshold"][0]),
                         "flag_rate": float(flags.mean()), "nominal_flag_rate": p_nom, "episodes": n_ep,
                         "fa_episodes": int(is_fa.sum()), "ta_episodes": int(is_ta.sum()),
                         "other_labeled_episodes": int(is_other.sum()), "multi_event_episodes": int(n_multi.sum()),
                         "scoreable_events": n_events, "detected_events": n_det,
                         "event_recall": n_det / n_events if n_events else float("nan"),
                         "chance_event_recall": C.chance_recall([len(e["test_pos"]) for e in scoreable], p_nom),
                         "window_auroc": float(roc_auc_score(yw, sw)) if yw.any() and (~yw).any() else float("nan"),
                         "window_ap": float(average_precision_score(yw, sw)) if yw.any() else float("nan"),
                         "muc_equal_score_only": muc_score,
                         "muc_equal_attainable": C.attainable_equal(ep_event_ids, n_events, n_ep),
                         **{f"vor_all_{k}": v for k, v in vor_all.items()},
                         **{f"vor_anomalies_{k}": v for k, v in vor_anom.items()},
                         "stale_flagged_window_share": float(stale_test[flags].mean()) if flags.any() else float("nan"),
                         "stale_episode_share": float(ep_stale.mean()) if n_ep else float("nan"),
                         "stale_fa_episode_share": float(ep_stale[is_fa].mean()) if is_fa.any() else float("nan"),
                         "stale_detected_peak_share": float(np.mean([stale_test[p] for _, p in det_events])) if det_events else float("nan"),
                         "episodes_stale_excluded": int(keep.sum()), "fa_episodes_stale_excluded": int((is_fa & keep).sum()),
                         "muc_equal_score_only_stale_excluded": queue_muc(tau[keep], 20260926 + 1000 * mi + 999, ids_keep, n_events),
                         "attr_capped_by_rep": attr_capped})
        for y in np.unique(test_year):
            wy = test_year == y
            ey = ep_year == y
            lens = ep_len[ey]
            year_rows.append({"set": set_name, "model": model_name, "year": int(y), "valid_test_windows": int(wy.sum()),
                              "flag_rate": float(flags[wy].mean()), "episodes": int(ey.sum()),
                              "episode_len_median": float(np.median(lens)) if len(lens) else float("nan"),
                              "episode_len_p90": float(np.quantile(lens, 0.9)) if len(lens) else float("nan"),
                              "episode_len_max": int(lens.max()) if len(lens) else 0,
                              "multi_event_episodes": int(n_multi[ey].sum()) if n_ep else 0,
                              "stale_window_share": float(stale_test[wy].mean())})
        for sp_name, sp_ev, sp_win, sp_ep in (("pre_drift", ~ev_drift, ~test_drift, ~ep_drift),
                                               ("drift", ev_drift, test_drift, ep_drift)):
            idx_ep = np.flatnonzero(sp_ep)
            ids_sp, n_sp = remap_events([ep_event_ids[k] for k in idx_ep], sp_ev)
            sub_rows.append({"set": set_name, "model": model_name, "subperiod": sp_name, "events": int(sp_ev.sum()),
                             "detected_events": int(np.sum(np.asarray(detected)[sp_ev])) if n_events else 0,
                             "valid_test_windows": int(sp_win.sum()),
                             "flag_rate": float(flags[sp_win].mean()) if sp_win.any() else float("nan"),
                             "episodes": int(len(idx_ep)), "fa_episodes": int(is_fa[idx_ep].sum()),
                             "muc_equal_score_only": queue_muc(tau[idx_ep], 20260926 + 1000 * mi + 999, ids_sp, n_sp),
                             "stale_window_share": float(stale_test[sp_win].mean()) if sp_win.any() else float("nan")})
        if n_ep == 0:
            continue
        # episode masses: peak (four sources) and aggregated (raw, feature, closed-form native)
        reps = [np.load(attr_paths(cfg, set_name, model_name, rep)[0]) for rep in range(cfg.reps)]
        sub = reps[0]["subsample"]
        nat_rows = reps[0]["native_rows"]
        for r in reps[1:]:
            assert np.array_equal(r["subsample"], sub) and np.array_equal(r["native_rows"], nat_rows)
        nat_mass = np.full((n_ep, nch), np.nan)
        nat_mass[nat_rows] = C.mean_mass(np.asarray([r["native"][nat_rows] for r in reps]))[0]
        occ_mass = np.full((n_ep, nch), np.nan)
        occ_mass[sub] = C.mean_mass(np.asarray([r["occlusion"][sub] for r in reps]))[0]
        all_rows = np.arange(n_ep, dtype=np.int64)
        sources = [("peak", "native", nat_mass, nat_rows), ("peak", "occlusion", occ_mass, sub),
                   ("peak", "raw", ep["peak_raw"], all_rows), ("peak", "feature", ep["peak_feature"], all_rows),
                   ("aggregated", "raw", ep["agg_raw"], all_rows), ("aggregated", "feature", ep["agg_feature"], all_rows)]
        if model_name in CLOSED_FORM:
            agg_nat, _ = C.combine_replicate_aggregates([r["native_agg"] for r in reps],
                                                        [r["native_agg_rep_deg"] for r in reps],
                                                        [r["native_agg_win_deg"] for r in reps])
            sources.append(("aggregated", "native", agg_nat, all_rows))
        model_rows = []
        for k in range(n_ep):
            row = {"set": set_name, "model": model_name, "episode": k, "start_window": int(test_idx[ep_start[k]]),
                   "peak_window": int(ep["ep_peak_window"][k]), "length_windows": int(ep_len[k]), "tau": float(ep["tau"][k]),
                   "fa": bool(is_fa[k]), "ta": bool(is_ta[k]), "other_labeled": bool(is_other[k]),
                   "n_events": len(ep_event_ids[k]), "subperiod": "drift" if ep_drift[k] else "pre_drift",
                   "year": int(ep_year[k]), "peak_stale": bool(ep_stale[k])}
            for kind, src, M, rows in sources:
                if np.isfinite(M[k]).all():
                    top = chans[int(np.argmax(M[k]))]
                    row[f"top_{kind}_{src}"] = top
                    row[f"top_{kind}_{src}_guarded"] = top in guarded_ch
            model_rows.append(row)
        ep_frames.append(pd.DataFrame(model_rows))
        del model_rows
        variants = {"all": np.ones(n_ep, bool), "stale_excluded": ~ep_stale, "pre_drift": ~ep_drift, "drift": ep_drift}
        for kind, src, M, rows in sources:
            avail = np.zeros(n_ep, bool)
            avail[rows] = True
            for vname, vmask in variants.items():
                base = avail & vmask
                for label, sel in (("false_alarm", is_fa), ("true_alarm", is_ta)):
                    s = base & sel
                    if s.any():
                        e2_rows.append({"set": set_name, "model": model_name, "mass": kind, "source": src,
                                        "variant": vname, "episodes": label, "capped_subsample": bool(len(rows) < n_ep),
                                        **e2_stats(M[s], chans)})
        if set_name != "primary":
            continue
        for kind, src, M, rows in sources:
            if kind != "peak":
                continue
            avail = np.zeros(n_ep, bool)
            avail[rows] = True
            for vname, vmask in variants.items():
                idx = np.flatnonzero(avail & vmask)
                if len(idx) < 3:
                    continue
                ids_v = [ep_event_ids[k] for k in idx]
                n_ev_v = n_events
                if vname in ("pre_drift", "drift"):
                    ids_v, n_ev_v = remap_events(ids_v, ev_drift if vname == "drift" else ~ev_drift)
                runner.phase(f"e3_{model_name}_{src}_{vname}")
                rows_k, summ = e3_block(M[idx], tau[idx], is_fa[idx], ids_v, n_ev_v, mi, chans)
                for r in rows_k:
                    e3_rows.append({"model": model_name, "source": src, "variant": vname, **r})
                e3_summary.append({"model": model_name, "source": src, "variant": vname,
                                   "capped_subsample": bool(len(rows) < n_ep), **summ})
    runner.phase("write")
    outs = eval_paths(cfg, set_name)
    e1 = pd.DataFrame(e1_rows)
    atomic_csv(outs[0], e1 if len(e1) else pd.DataFrame(columns=["set", "model", "event", "source", "auroc"]))
    atomic_csv(outs[1], mass_summary_rows(e1))
    atomic_csv(outs[2], pd.DataFrame(det_rows))
    atomic_csv(outs[3], pd.DataFrame(year_rows))
    atomic_csv(outs[4], pd.DataFrame(sub_rows))
    atomic_csv(outs[5], pd.DataFrame(e2_rows))
    atomic_csv(outs[6], pd.concat(ep_frames, ignore_index=True) if ep_frames else pd.DataFrame())
    summary = {"set": set_name, "channels": nch, "test_events_total": len(events), "scoreable_events": n_events,
               "scoreable_by_category": pd.Series([e["category"] for e in scoreable]).value_counts().to_dict(),
               "scoreable_by_subperiod": {"pre_drift": int((~ev_drift).sum()), "drift": int(ev_drift.sum())},
               "events_with_m_equal_C": int(sum(1 for e in scoreable if e["m"] == nch)),
               "events_with_0_lt_m_lt_C": int(sum(1 for e in scoreable if 0 < e["m"] < nch)),
               "events_without_valid_window": int(sum(1 for e in scoreable if len(e["test_pos"]) == 0)),
               "overlapping_test_event_pairs": int(overlap_pairs), "test_label_rows": int(len(test_segs)),
               "test_gap_label_rows": int((test_segs["Category"] == C.GAP_CATEGORY).sum()),
               "stale_valid_test_window_share": {"pre_drift": float(stale_test[~test_drift].mean()) if (~test_drift).any() else None,
                                                 "drift": float(stale_test[test_drift].mean()) if test_drift.any() else None},
               "guarded_feature_channels": stats["guarded_feature_channels"],
               "guarded_raw_channels": stats["guarded_raw_channels"], "opened_test_labels_at": now_iso()}
    if set_name == "primary":
        atomic_csv(outs[8], pd.DataFrame(e3_rows))
        atomic_csv(outs[9], pd.DataFrame(e3_summary))
    atomic_json(outs[7], summary)
    return {k: summary[k] for k in ("scoreable_events", "events_with_0_lt_m_lt_C", "overlapping_test_event_pairs")}


# ---------------------------------------------------------------- unit: decision (H-E1)
def decision_paths(cfg: Config) -> list[Path]:
    return [cfg.run_dir / "results" / "DECISION_H_E1.json"]


def unit_decision(cfg: Config, runner: Runner):
    e1 = pd.read_csv(cfg.run_dir / "results" / "primary" / "E1_event_rows.csv")
    delta, per = 0.06, []
    for model_name in C.PRIMARY_MODELS:
        mi = C.MODELS.index(model_name)
        sub = e1[(e1["model"] == model_name) & e1["source"].isin(["feature", "native"])]
        piv = sub.pivot_table(index="event", columns="source", values="auroc", aggfunc="first").dropna().sort_index()
        classes = sub.drop_duplicates("event").set_index("event")["class"].reindex(piv.index).astype(str).to_numpy()
        n = int(len(piv))
        row = {"model": model_name, "model_index": mi, "n_events": n}
        if n == 0:
            row.update({"status": "NOT_EVALUABLE_N", "passes": False})
            per.append(row)
            continue
        nat = piv["native"].to_numpy(dtype=float)
        feat = piv["feature"].to_numpy(dtype=float)
        d = feat - nat
        assay_lb, _ = C.bootstrap_mean_lb(nat, 20260926 + 100 + mi)
        lb, boots = C.bootstrap_mean_lb(d, 20260926 + mi)
        t_lb = C.t_lower_bound(d)
        feat_lb, _ = C.bootstrap_mean_lb(feat, 20260926 + 300 + mi)
        cl_lb, n_cl = C.cluster_bootstrap_lb(d, classes, 20260926 + 200 + mi)
        if n < 30:
            status = "NOT_EVALUABLE_N"
        elif not assay_lb > 0.5:
            status = "NOT_INFORMATIVE"
        else:
            status = "EVALUABLE"
        row.update({"status": status, "native_mean_auroc": float(nat.mean()), "assay_lower_bound": assay_lb,
                    "assay_passes": bool(assay_lb > 0.5), "assay_seed": 20260926 + 100 + mi,
                    "feature_mean_auroc": float(feat.mean()), "feature_lower_bound_vs_chance": feat_lb,
                    "mean_difference": float(d.mean()), "lower_bound_one_sided_95": lb, "t_lower_bound_one_sided_95": t_lb,
                    "passes": bool(status == "EVALUABLE" and lb > -delta),
                    "t_passes": bool(status == "EVALUABLE" and t_lb > -delta),
                    "distance_to_margin": lb + delta, "bootstrap_seed": 20260926 + mi, "bootstrap_resamples": C.N_BOOT,
                    "two_sided_95": [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))],
                    "class_cluster_lower_bound": cl_lb, "class_clusters": n_cl, "class_cluster_seed": 20260926 + 200 + mi})
        per.append(row)
    k = sum(1 for r in per if r["status"] == "EVALUABLE")
    passes = sum(1 for r in per if r.get("passes"))
    need = int(np.ceil(0.8 * k)) if k else None
    verdict = "NOT_EVALUABLE" if k < 3 else ("SUPPORTED" if passes >= need else "NOT_SUPPORTED")
    t_passes = sum(1 for r in per if r.get("t_passes"))
    t_verdict = "NOT_EVALUABLE" if k < 3 else ("SUPPORTED" if t_passes >= need else "NOT_SUPPORTED")
    out = {"hypothesis": "H-E1", "margin_delta": delta,
           "rule": "evaluable iff n >= 30 and native assay LB > 0.5; k < 3 NOT_EVALUABLE; else SUPPORTED iff passes >= ceil(0.8 k)",
           "evaluable_detectors": k, "passes": passes, "required_passes": need, "verdict": verdict,
           "student_t_sensitivity": {"passes": t_passes, "verdict": t_verdict, "agrees_with_primary": t_verdict == verdict},
           "per_detector": per, "decided_at": now_iso()}
    atomic_json(decision_paths(cfg)[0], out)
    return {"verdict": verdict, "k": k, "passes": passes}


# ---------------------------------------------------------------- plan and main loop
def plan_units(cfg: Config) -> list[tuple[str, callable, callable]]:
    units = []
    for ch in cfg.channel_sets["primary"]:
        units.append((f"prep:{ch}", (lambda ch=ch: lambda r: unit_prep(cfg, r, ch))(), (lambda ch=ch: lambda: prep_paths(cfg, ch))()))
    for s in cfg.channel_sets:
        units.append((f"stdz:{s}", (lambda s=s: lambda r: unit_stdz(cfg, r, s))(), (lambda s=s: lambda: stdz_paths(cfg, s))()))
    for s in cfg.channel_sets:
        for m in cfg.models:
            for rep in range(cfg.reps):
                units.append((f"fit:{s}:{m}:{rep}", (lambda s=s, m=m, rep=rep: lambda r: unit_fit(cfg, r, s, m, rep))(),
                              (lambda s=s, m=m, rep=rep: lambda: fit_paths(cfg, s, m, rep))()))
    for s in cfg.channel_sets:
        for m in cfg.models:
            units.append((f"episodes:{s}:{m}", (lambda s=s, m=m: lambda r: unit_episodes(cfg, r, s, m))(),
                          (lambda s=s, m=m: lambda: episode_paths(cfg, s, m))()))
    for s in cfg.channel_sets:
        for m in cfg.models:
            for rep in range(cfg.reps):
                units.append((f"attr_episode:{s}:{m}:{rep}",
                              (lambda s=s, m=m, rep=rep: lambda r: unit_attr_episode(cfg, r, s, m, rep))(),
                              (lambda s=s, m=m, rep=rep: lambda: attr_paths(cfg, s, m, rep))()))
    for s in cfg.channel_sets:
        units.append((f"eval:{s}", (lambda s=s: lambda r: unit_eval(cfg, r, s))(), (lambda s=s: lambda: eval_paths(cfg, s))()))
    if "primary" in cfg.channel_sets:
        units.append(("decision", lambda r: unit_decision(cfg, r), lambda: decision_paths(cfg)))
    return units


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "status", "plan"])
    parser.add_argument("--only", default=None, help="run only units whose id starts with this prefix")
    parser.add_argument("--controlled-stop-after", type=int, default=None)
    parser.add_argument("--controlled-stop-marker", default=None,
                        help="stop only while this marker file is absent; it is created at the controlled stop")
    parser.add_argument("--stop-before-fit", action="store_true", help="stop before the first fit unit (freeze gate)")
    args = parser.parse_args()
    if args.controlled_stop_marker and Path(args.controlled_stop_marker).exists():
        args.controlled_stop_after = None
    cfg = default_config()
    runner = Runner(cfg)
    units = plan_units(cfg)
    runner.planned = len(units)
    if args.command == "plan":
        atomic_json(cfg.run_dir / "UNIT_PLAN.json", {"run_id": RUN_ID, "units": [u[0] for u in units], "count": len(units)})
        print(len(units))
        return 0
    if args.command == "status":
        done = [u[0] for u in units if runner.validated(u[0])]
        print(json.dumps({"planned": len(units), "validated": len(done)}, indent=1))
        return 0
    hb = threading.Thread(target=runner._heartbeat_loop, daemon=True)
    hb.start()
    runner.terminal("RUNNING", -1)
    new_done = 0
    try:
        for unit_id, fn, outs in units:
            if args.only and not unit_id.startswith(args.only):
                if runner.validated(unit_id):
                    runner.completed += 1
                continue
            if args.stop_before_fit and unit_id.startswith("fit:"):
                runner.terminal("COMPLETED", 0, reason="scope pre-freeze units only; stopped before the first fit "
                                                      "unit (full-data fits start only after the public freeze)")
                print("STOPPED_AT_FREEZE_GATE", flush=True)
                return 0
            ran = runner.execute(unit_id, lambda fn=fn: fn(runner), outs)
            if ran:
                new_done += 1
                if args.controlled_stop_after is not None and new_done >= args.controlled_stop_after:
                    if args.controlled_stop_marker:
                        Path(args.controlled_stop_marker).write_text(now_iso(), encoding="utf-8")
                    runner.terminal("CONTROLLED_STOP", CONTROLLED_EXIT, reason="durability smoke")
                    print("CONTROLLED_STOP", flush=True)
                    return CONTROLLED_EXIT
        runner.terminal("COMPLETED", 0, reason=f"scope --only {args.only}" if args.only else "all planned units")
        return 0
    finally:
        runner._stop.set()
        runner.write_heartbeat()


if __name__ == "__main__":
    sys.exit(main())

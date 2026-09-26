"""Core computations for the ESA-ADB Mission1 bounded arm.

Operation: f07-rb4-esa-adb-revision-20260926

This module holds the scientific definitions only (data access, grid, windows,
features, masks, models, scores, masses, metrics). Orchestration, checkpoints,
heartbeat and resume live in esa_arm.py. Definitions mirror the synthetic core:
github-telemetry_alarm_xai/code/common.py and models.py,
experiments/2026-09-04_codex_local_fresh_validation_candidate/code_snapshot/
run_criticality_unit.py and criticality_analysis_v4.py, and
experiments/2026-09-04_codex_vps_matched_information/prepare_inputs.py.
Declared deviations are listed in the frozen protocol.
"""
from __future__ import annotations

import io
import math
import zipfile
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

GRID_NS = 30 * 1_000_000_000
W = 20
STRIDE = 5
NFEAT = 4
WINDOW_SPAN_NS = (W - 1) * GRID_NS
WINDOW_STEP_NS = STRIDE * GRID_NS
VAL_START_NS = int(pd.Timestamp("2006-10-01T00:00:00").value)
TEST_START_NS = int(pd.Timestamp("2007-01-01T00:00:00").value)
DRIFT_START_NS = int(pd.Timestamp("2012-07-01T00:00:00").value)  # VOR Table 6: last 18 months drift
STALE_S = 3600.0  # stale iff max channel age > 3,600 s (4 x the slowest 900 s cadence)
CAP_EPISODES = 20_000  # model-call mass cap per set and model
GUARD_REL = 1e-8  # zero-variance guard: sd <= GUARD_REL * max(1, |mean|)
N_BOOT = 2000
EVENT_CATEGORIES = ("Anomaly", "Rare Event")
GAP_CATEGORY = "Communication Gap"
MODELS = ["lr", "dtree", "iforest", "hgb", "pca", "ae"]
PRIMARY_MODELS = ["lr", "iforest", "hgb", "pca", "ae"]
SUPERVISED = {"lr": True, "dtree": True, "hgb": True, "iforest": False, "pca": False, "ae": False}
N_FIT = 100_000
N_BG = 50_000
BG_SEED = 20_260_926
N_REP = 3
OCC_DRAWS = 8
EVENT_QUERY_OFFSET = 700_001
EPISODE_QUERY_OFFSET = 1_400_009
FRACTIONS = (0.05, 0.10, 0.20, 0.40)
PRIMARY_MAX_LOAD = 0.40
TIE_DRAWS = 100


# ---------------------------------------------------------------- data access
def load_channel_series(zip_path: Path, channel: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (timestamps ns int64, values float64) of one channel pickle."""
    member = f"ESA-Mission1/channels/{channel}.zip"
    with zipfile.ZipFile(zip_path) as archive:
        blob = archive.read(member)
    with zipfile.ZipFile(io.BytesIO(blob)) as inner:
        names = inner.namelist()
        if len(names) != 1:
            raise RuntimeError(f"{member}: expected one inner member, got {names}")
        frame = pd.read_pickle(io.BytesIO(inner.read(names[0])))
    index = pd.DatetimeIndex(frame.index)
    if index.tz is not None:
        index = index.tz_convert(None)
    t = index.asi8.astype(np.int64)
    v = np.asarray(frame.iloc[:, 0], dtype=np.float64)
    del frame, blob
    if len(t) > 1 and not np.all(np.diff(t) > 0):
        # keep the last occurrence of duplicate timestamps; require non-decreasing order
        if not np.all(np.diff(t) >= 0):
            raise RuntimeError(f"{channel}: timestamps not sorted")
        keep = np.ones(len(t), dtype=bool)
        keep[:-1] = t[1:] != t[:-1]
        t, v = t[keep], v[keep]
    return t, v


def load_meta_table(meta_dir: Path, zip_path: Path, name: str) -> pd.DataFrame:
    """Read a metadata CSV extracted by 7-Zip after checking CRC32 and size against the archive."""
    member = f"ESA-Mission1/{name}"
    with zipfile.ZipFile(zip_path) as archive:
        info = archive.getinfo(member)
    blob = (meta_dir / name).read_bytes()
    if len(blob) != info.file_size or (zlib.crc32(blob) & 0xFFFFFFFF) != info.CRC:
        raise RuntimeError(f"{name}: extracted bytes do not match the archive record")
    return pd.read_csv(io.BytesIO(blob))


def label_segments(labels: pd.DataFrame, types: pd.DataFrame) -> pd.DataFrame:
    """Return segments with integer ns bounds and category."""
    frame = labels.merge(types[["ID", "Category"]], on="ID", how="left")
    if frame["Category"].isna().any():
        raise RuntimeError("label rows without category")
    start = pd.to_datetime(frame["StartTime"], utc=True).dt.tz_localize(None)
    end = pd.to_datetime(frame["EndTime"], utc=True).dt.tz_localize(None)
    out = pd.DataFrame({
        "ID": frame["ID"].astype(str),
        "Channel": frame["Channel"].astype(str),
        "S": start.astype("int64").to_numpy(),
        "E": end.astype("int64").to_numpy(),
        "Category": frame["Category"].astype(str),
    })
    if (out["E"] < out["S"]).any():
        raise RuntimeError("segment with end before start")
    return out


def pre_evaluation_segments(segments: pd.DataFrame) -> pd.DataFrame:
    """Test-label lock: keep segments starting before the test boundary, clipped at it."""
    keep = segments[segments["S"] < TEST_START_NS].copy()
    keep["E"] = np.minimum(keep["E"].to_numpy(), TEST_START_NS - 1)
    return keep.reset_index(drop=True)


# ---------------------------------------------------------------- grid and windows
def grid_bounds(first_ns: list[int], last_ns: list[int]) -> tuple[int, int, int]:
    start = (min(first_ns) // GRID_NS) * GRID_NS
    end = -((-max(last_ns)) // GRID_NS) * GRID_NS
    n_grid = (end - start) // GRID_NS + 1
    return int(start), int(end), int(n_grid)


def n_windows(n_grid: int) -> int:
    return (n_grid - W) // STRIDE + 1


def window_start_ns(grid_start: int, k: np.ndarray) -> np.ndarray:
    return grid_start + np.asarray(k, dtype=np.int64) * WINDOW_STEP_NS


def zoh_values(t: np.ndarray, v: np.ndarray, grid_ns: np.ndarray) -> np.ndarray:
    """Zero-order hold, forward only: last sample with timestamp <= grid time; NaN before the first."""
    idx = np.searchsorted(t, grid_ns, side="right") - 1
    out = np.full(len(grid_ns), np.nan, dtype=np.float64)
    ok = idx >= 0
    out[ok] = v[idx[ok]]
    return out


def window_features_chunk(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """x: grid values covering whole windows (length (n-1)*STRIDE + W). Returns (n, 4) features and valid mask.

    Same arithmetic as common.window_features: mean, population sd (numpy std), least-squares
    slope on the centered index, last-minus-first delta.
    """
    from numpy.lib.stride_tricks import sliding_window_view

    seg = sliding_window_view(x, W)[::STRIDE]
    seg = np.array(seg, dtype=np.float64)  # materialize the chunk (bounded by the caller)
    t = np.arange(W) - (W - 1) / 2.0
    denom = float((t ** 2).sum())
    mu = seg.mean(axis=1)
    sd = seg.std(axis=1)
    slope = ((seg - mu[:, None]) * t[None, :]).sum(axis=1) / denom
    delta = seg[:, -1] - seg[:, 0]
    feats = np.stack([mu, sd, slope, delta], axis=1)
    valid = np.isfinite(seg).all(axis=1)
    return feats, valid


def window_ages(t: np.ndarray, grid_start: int, k0: int, k1: int) -> np.ndarray:
    """Staleness age (s) of windows k0..k1-1: window end minus the last original sample at or before it.

    +inf when the channel has no sample at or before the window end (such windows are invalid).
    """
    we = grid_start + np.arange(k0, k1, dtype=np.int64) * WINDOW_STEP_NS + WINDOW_SPAN_NS
    idx = np.searchsorted(t, we, side="right") - 1
    age = np.full(len(we), np.inf, dtype=np.float64)
    ok = idx >= 0
    age[ok] = (we[ok] - t[idx[ok]]) / 1e9
    return age


def guarded(sd: np.ndarray, mean: np.ndarray) -> np.ndarray:
    """Zero-variance guard: population sd <= GUARD_REL * max(1, |mean|)."""
    sd = np.asarray(sd, dtype=float)
    mean = np.asarray(mean, dtype=float)
    return sd <= GUARD_REL * np.maximum(1.0, np.abs(mean))


def window_mean_abs_z(x: np.ndarray, mu: float, sd: float) -> np.ndarray:
    """Raw-deviation mass component: window mean of |x - mu| / (sd + 1e-9)."""
    from numpy.lib.stride_tricks import sliding_window_view

    z = np.abs((x - mu) / (sd + 1e-9))
    seg = sliding_window_view(z, W)[::STRIDE]
    return np.asarray(seg.mean(axis=1), dtype=np.float64)


def segment_window_ranges(S: np.ndarray, E: np.ndarray, grid_start: int, nwin: int) -> tuple[np.ndarray, np.ndarray]:
    """Inclusive window-index range overlapping each closed segment [S, E] (ws <= E and ws + span >= S)."""
    lo = np.ceil((S - WINDOW_SPAN_NS - grid_start) / WINDOW_STEP_NS).astype(np.int64)
    hi = np.floor((E - grid_start) / WINDOW_STEP_NS).astype(np.int64)
    lo = np.clip(lo, 0, nwin)
    hi = np.clip(hi, -1, nwin - 1)
    return lo, hi


def mark_ranges(lo: np.ndarray, hi: np.ndarray, n: int) -> np.ndarray:
    diff = np.zeros(n + 1, dtype=np.int64)
    ok = hi >= lo
    np.add.at(diff, lo[ok], 1)
    np.add.at(diff, hi[ok] + 1, -1)
    return np.cumsum(diff[:-1]) > 0


def grid_labeled_mask(S: np.ndarray, E: np.ndarray, grid_start: int, n_grid: int) -> np.ndarray:
    """Grid samples lying inside any closed segment [S, E]."""
    lo = np.ceil((S - grid_start) / GRID_NS).astype(np.int64)
    hi = np.floor((E - grid_start) / GRID_NS).astype(np.int64)
    lo = np.clip(lo, 0, n_grid)
    hi = np.clip(hi, -1, n_grid - 1)
    return mark_ranges(lo, hi, n_grid)


def window_periods(grid_start: int, nwin: int) -> np.ndarray:
    """0 fit, 1 validation, 2 test, 3 boundary-straddling (excluded)."""
    ws = window_start_ns(grid_start, np.arange(nwin))
    we = ws + WINDOW_SPAN_NS
    period = np.full(nwin, 3, dtype=np.int8)
    period[we < VAL_START_NS] = 0
    period[(ws >= VAL_START_NS) & (we < TEST_START_NS)] = 1
    period[ws >= TEST_START_NS] = 2
    return period


# ---------------------------------------------------------------- models (models.py with d = 4C)
class AE:
    def __init__(self, d: int, seed: int):
        import torch
        import torch.nn as nn

        torch.manual_seed(seed)
        self.net = nn.Sequential(nn.Linear(d, 24), nn.ReLU(), nn.Linear(24, 8), nn.ReLU(),
                                 nn.Linear(8, 24), nn.ReLU(), nn.Linear(24, d))

    def fit(self, X: np.ndarray):
        import torch

        torch.set_num_threads(1)
        Xt = torch.tensor(X, dtype=torch.float32)
        opt = torch.optim.Adam(self.net.parameters(), lr=1e-3)
        for _ in range(60):
            perm = torch.randperm(len(Xt))
            for i in range(0, len(Xt), 256):
                b = Xt[perm[i:i + 256]]
                loss = ((self.net(b) - b) ** 2).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
        return self

    def recon(self, X: np.ndarray) -> np.ndarray:
        import torch

        with torch.no_grad():
            return self.net(torch.tensor(X, dtype=torch.float32)).numpy()


def build_and_fit(name: str, rep_seed: int, X: np.ndarray, y: np.ndarray | None):
    from sklearn.decomposition import PCA
    from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier

    if name == "lr":
        return LogisticRegression(max_iter=2000, C=1.0).fit(X, y)
    if name == "dtree":
        return DecisionTreeClassifier(max_depth=4, random_state=rep_seed).fit(X, y)
    if name == "hgb":
        return HistGradientBoostingClassifier(max_iter=150, max_depth=4, random_state=rep_seed,
                                              early_stopping=False).fit(X, y)
    if name == "iforest":
        return IsolationForest(n_estimators=150, random_state=rep_seed).fit(X)
    if name == "pca":
        return PCA(n_components=10, svd_solver="covariance_eigh", random_state=rep_seed).fit(X)
    if name == "ae":
        return AE(X.shape[1], rep_seed).fit(X)
    raise ValueError(name)


def score(name: str, model, Z: np.ndarray) -> np.ndarray:
    if SUPERVISED[name]:
        return model.predict_proba(Z)[:, 1]
    if name == "iforest":
        return -model.score_samples(Z)
    if name == "pca":
        R = model.inverse_transform(model.transform(Z))
        return ((Z - R) ** 2).mean(1)
    if name == "ae":
        return ((Z - model.recon(Z)) ** 2).mean(1)
    raise ValueError(name)


def channel_aggregate(att: np.ndarray, nch: int) -> np.ndarray:
    A = np.abs(att).reshape(att.shape[0], NFEAT, nch)
    return A.sum(1)


def native_attr(name: str, model, Zq: np.ndarray, bg_mean: np.ndarray, nch: int, explainer=None) -> np.ndarray:
    if name == "lr":
        contrib = model.coef_[0][None, :] * (Zq - bg_mean[None, :])
        return channel_aggregate(contrib, nch)
    if name in ("dtree", "hgb", "iforest"):
        sv = explainer.shap_values(Zq, check_additivity=False)
        if isinstance(sv, list):
            sv = sv[1] if len(sv) > 1 else sv[0]
        sv = np.asarray(sv)
        if sv.ndim == 3:
            sv = sv[:, :, 1]
        return channel_aggregate(sv, nch)
    if name == "pca":
        R = model.inverse_transform(model.transform(Zq))
        return channel_aggregate((Zq - R) ** 2, nch)
    if name == "ae":
        return channel_aggregate((Zq - model.recon(Zq)) ** 2, nch)
    raise ValueError(name)


def tree_explainer(name: str, model):
    if name not in ("dtree", "hgb", "iforest"):
        return None
    import shap

    return shap.TreeExplainer(model, feature_perturbation="tree_path_dependent")


def occlusion_attr(name: str, model, Zq: np.ndarray, draws: np.ndarray, nch: int) -> np.ndarray:
    """models.occlusion_attr with the eight draws supplied by the caller (drawn once per query set)."""
    k, d = Zq.shape
    n_draws = len(draws)
    base = score(name, model, Zq)
    out = np.zeros((k, nch))
    for ch in range(nch):
        cols = [f * nch + ch for f in range(NFEAT)]
        big = np.repeat(Zq, n_draws, axis=0)
        for j in range(n_draws):
            big[j::n_draws, cols] = draws[j][cols]
        s = score(name, model, big).reshape(k, n_draws)
        out[:, ch] = base - s.mean(1)
    return np.maximum(out, 0.0)


def occlusion_draws(background: np.ndarray, query_offset: int, replicate: int) -> np.ndarray:
    rng = np.random.default_rng(1_000_003 * (0 + query_offset) + 10_007 * replicate + 29)
    return background[rng.choice(len(background), OCC_DRAWS)]


# ---------------------------------------------------------------- masses
def normalise_mass(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mass = np.maximum(np.asarray(values, dtype=float), 0.0)
    totals = mass.sum(axis=-1, keepdims=True)
    degenerate = np.squeeze(totals <= 1e-12, axis=-1)
    safe = np.divide(mass, totals, out=np.zeros_like(mass), where=totals > 1e-12)
    nch = mass.shape[-1]
    safe = np.where(np.expand_dims(degenerate, -1), 1.0 / nch, safe)
    return safe, np.asarray(degenerate, dtype=bool)


def mean_mass(replicate_attributions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rep_mass, rep_deg = normalise_mass(replicate_attributions)
    m = rep_mass.mean(axis=0)
    m, mean_deg = normalise_mass(m)
    return m, np.all(rep_deg, axis=0) | mean_deg


def feature_mass(Zq: np.ndarray, nch: int) -> np.ndarray:
    return np.abs(Zq).reshape(-1, NFEAT, nch).sum(axis=1)


def tail_surprisal(query: np.ndarray, nominal_validation: np.ndarray) -> np.ndarray:
    """criticality_analysis_v4.tail_surprisal, verbatim arithmetic."""
    query = np.asarray(query, dtype=float)
    reference = np.sort(np.asarray(nominal_validation, dtype=float))
    count_ge = len(reference) - np.searchsorted(reference, query, side="left")
    fractional = np.zeros(len(query), dtype=float)
    for bin_id in np.unique(count_ge):
        ids = np.where(count_ge == bin_id)[0]
        values = query[ids]
        order = np.argsort(-values, kind="stable")
        ranks = np.empty(len(ids), dtype=float)
        cursor = 0
        while cursor < len(order):
            stop = cursor + 1
            while stop < len(order) and values[order[stop]] == values[order[cursor]]:
                stop += 1
            ranks[order[cursor:stop]] = 0.5 * ((cursor + 1) + stop)
            cursor = stop
        fractional[ids] = ranks / (len(ids) + 1.0)
    p_value = (count_ge + fractional + 1.0) / (len(reference) + 1.0)
    return -np.log(p_value)


# ---------------------------------------------------------------- channel-evidence metrics
def ranking_auroc(mass: np.ndarray, affected: np.ndarray) -> float:
    """Mann-Whitney AUROC of a channel mass against the affected set; ties at average rank."""
    from scipy.stats import rankdata

    m = int(affected.sum())
    c = len(mass)
    if m == 0 or m == c:
        return float("nan")
    ranks = rankdata(mass)  # ascending, average ties
    u = ranks[affected].sum() - m * (m + 1) / 2.0
    return float(u / (m * (c - m)))


def hit_at_k(mass: np.ndarray, affected: np.ndarray, k: int) -> int:
    order = np.argsort(-mass, kind="stable")
    return int(affected[order[:k]].any())


def best_affected_rank(mass: np.ndarray, affected: np.ndarray) -> int:
    order = np.argsort(-mass, kind="stable")
    ranks = np.empty(len(mass), dtype=int)
    ranks[order] = np.arange(1, len(mass) + 1)
    return int(ranks[affected].min())


def r_precision(mass: np.ndarray, affected: np.ndarray) -> float:
    m = int(affected.sum())
    order = np.argsort(-mass, kind="stable")
    return float(affected[order[:m]].mean()) if m else float("nan")


def hit_chance(c: int, m: int, k: int) -> float:
    if m <= 0:
        return 0.0
    if c - m < k:
        return 1.0
    return 1.0 - math.comb(c - m, k) / math.comb(c, k)


def normalized_entropy(mass: np.ndarray) -> float:
    p = mass[mass > 0]
    return float(-(p * np.log(p)).sum() / np.log(len(mass)))


# ---------------------------------------------------------------- review-load utility
def tie_orderings(values: np.ndarray, seed: int) -> list[np.ndarray]:
    values = np.asarray(values, dtype=float)
    if len(np.unique(values)) == len(values):
        return [np.argsort(-values, kind="stable")]
    rng = np.random.default_rng(seed)
    return [np.lexsort((rng.random(len(values)), -values)) for _ in range(TIE_DRAWS)]


def captured_equal(selected: np.ndarray, episode_event_ids: list[list[int]], n_events: int) -> float:
    """Maximum one-to-one matching of alarms to events with unit utility."""
    rows = [episode_event_ids[int(e)] for e in selected]
    if all(len(r) <= 1 for r in rows):
        return float(len({r[0] for r in rows if r}))
    from scipy.optimize import linear_sum_assignment

    weights = np.zeros((len(rows), n_events), dtype=float)
    for i, r in enumerate(rows):
        for ev in r:
            weights[i, ev] = 1.0
    ri, ci = linear_sum_assignment(-weights)
    return float(weights[ri, ci].sum())


def load_counts(n: int) -> dict[float, int]:
    loads: dict[float, int] = {}
    for f in FRACTIONS:
        k = min(n, max(1, int(math.floor(f * n))))
        loads[k / n] = k
    return loads


def muc_auc_equal(ordering: np.ndarray, episode_event_ids: list[list[int]], n_events: int) -> float:
    n = len(ordering)
    if n < 3 or n_events == 0:
        return 0.0
    points = {0.0: 0.0}
    for x, k in load_counts(n).items():
        points[x] = captured_equal(ordering[:k], episode_event_ids, n_events) / n_events
    points[PRIMARY_MAX_LOAD] = points[max(points)]
    xs = np.asarray(sorted(points), dtype=float)
    ys = np.asarray([points[x] for x in xs], dtype=float)
    keep = xs <= PRIMARY_MAX_LOAD + 1e-12
    return float(np.trapezoid(ys[keep], xs[keep]) / PRIMARY_MAX_LOAD)


def fa_share_at(ordering: np.ndarray, is_fa: np.ndarray) -> dict[float, float]:
    n = len(ordering)
    out = {}
    for f in FRACTIONS:
        k = min(n, max(1, int(math.floor(f * n))))
        out[f] = float(is_fa[ordering[:k]].mean())
    return out


def attainable_equal(episode_event_ids: list[list[int]], n_events: int, n: int) -> float:
    """Ordering-free bound: credit the distinct detected events as early as the load allows."""
    detected = len({e for r in episode_event_ids for e in r})
    if n < 3 or n_events == 0:
        return 0.0
    points = {0.0: 0.0}
    for x, k in load_counts(n).items():
        points[x] = min(k, detected) / n_events
    points[PRIMARY_MAX_LOAD] = points[max(points)]
    xs = np.asarray(sorted(points), dtype=float)
    ys = np.asarray([points[x] for x in xs], dtype=float)
    keep = xs <= PRIMARY_MAX_LOAD + 1e-12
    return float(np.trapezoid(ys[keep], xs[keep]) / PRIMARY_MAX_LOAD)


# ---------------------------------------------------------------- v3: aggregated episode masses
class EpisodeAggregator:
    """Streaming form of run_criticality_unit._aggregate_episode_attributions for one replicate.

    Flagged windows arrive in order; ep_of_flag gives each flagged window's episode; weights are the
    windows' tail surprisals. Per-window masses are normalized, weighted by w / sum_episode(w) and summed;
    the episode sum is renormalized. Degeneracy follows the synthetic rule.
    """

    def __init__(self, ep_of_flag: np.ndarray, weights: np.ndarray, n_ep: int, nch: int):
        w = np.asarray(weights, dtype=np.float64)
        w_sum = np.bincount(ep_of_flag, weights=w, minlength=n_ep)
        self.w_norm = w / np.maximum(w_sum[ep_of_flag], 1e-12)
        self.ep = np.asarray(ep_of_flag, dtype=np.int64)
        self.acc = np.zeros((n_ep, nch), dtype=np.float64)
        self.any_nondegenerate = np.zeros(n_ep, dtype=bool)

    def add(self, lo: int, hi: int, attributions: np.ndarray) -> None:
        mass, deg = normalise_mass(attributions)
        np.add.at(self.acc, self.ep[lo:hi], mass * self.w_norm[lo:hi, None])
        np.logical_or.at(self.any_nondegenerate, self.ep[lo:hi], ~deg)

    def result(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(normalized replicate mass, replicate-degenerate, all-windows-degenerate)."""
        mass, deg = normalise_mass(self.acc)
        return mass, deg, ~self.any_nondegenerate


def combine_replicate_aggregates(masses: list[np.ndarray], rep_deg: list[np.ndarray],
                                 win_deg: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """_mean_mass over replicate aggregates with the synthetic episode-degeneracy rule."""
    mean = np.mean(np.asarray(masses), axis=0)
    mean, mean_deg = normalise_mass(mean)
    all_win = np.all(np.asarray(win_deg), axis=0)
    all_rep = np.all(np.asarray(rep_deg), axis=0)
    return mean, all_win | all_rep | mean_deg


# ---------------------------------------------------------------- v3: inference helpers
def bootstrap_mean_lb(values: np.ndarray, seed: int, n_boot: int = N_BOOT, q: float = 0.05) -> tuple[float, np.ndarray]:
    """Percentile lower bound of the mean: idx = default_rng(seed).integers(0, n, (n_boot, n))."""
    v = np.asarray(values, dtype=np.float64)
    n = len(v)
    if n == 0:
        return float("nan"), np.zeros(0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = v[idx].mean(axis=1)
    return float(np.quantile(means, q)), means


def t_lower_bound(values: np.ndarray, conf: float = 0.95) -> float:
    from scipy.stats import t as student_t

    v = np.asarray(values, dtype=np.float64)
    n = len(v)
    if n < 2:
        return float("nan")
    return float(v.mean() - student_t.ppf(conf, n - 1) * v.std(ddof=1) / math.sqrt(n))


def cluster_bootstrap_lb(values: np.ndarray, clusters: np.ndarray, seed: int, n_boot: int = N_BOOT,
                         q: float = 0.05) -> tuple[float, int]:
    """Resample clusters (sorted unique labels) with replacement; mean over all members of the drawn clusters."""
    v = np.asarray(values, dtype=np.float64)
    cl = np.asarray(clusters).astype(str)
    uniq = np.unique(cl)
    if len(uniq) == 0:
        return float("nan"), 0
    sums = np.asarray([v[cl == u].sum() for u in uniq])
    counts = np.asarray([(cl == u).sum() for u in uniq], dtype=np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return float(np.quantile(means, q)), int(len(uniq))


def chance_recall(n_windows_per_event: np.ndarray, p: float) -> float:
    n = np.asarray(n_windows_per_event, dtype=np.float64)
    if len(n) == 0:
        return float("nan")
    return float(np.mean(1.0 - (1.0 - p) ** n))


# ---------------------------------------------------------------- v3: time-domain intervals and VOR Eq. 1-2
def merge_intervals(starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    s = np.asarray(starts, dtype=np.int64)
    e = np.asarray(ends, dtype=np.int64)
    if len(s) == 0:
        return s, e
    order = np.argsort(s, kind="stable")
    s, e = s[order], e[order]
    out_s, out_e = [int(s[0])], [int(e[0])]
    for a, b in zip(s[1:], e[1:]):
        if a <= out_e[-1]:
            out_e[-1] = max(out_e[-1], int(b))
        else:
            out_s.append(int(a))
            out_e.append(int(b))
    return np.asarray(out_s, dtype=np.int64), np.asarray(out_e, dtype=np.int64)


def clip_intervals(s: np.ndarray, e: np.ndarray, t0: int, t1: int) -> tuple[np.ndarray, np.ndarray]:
    s2 = np.maximum(s, t0)
    e2 = np.minimum(e, t1)
    keep = e2 > s2
    return s2[keep], e2[keep]


def intersection_length(a_s, a_e, b_s, b_e) -> int:
    """Total length of the intersection of two merged (sorted, disjoint) interval lists."""
    i = j = 0
    total = 0
    while i < len(a_s) and j < len(b_s):
        lo = max(int(a_s[i]), int(b_s[j]))
        hi = min(int(a_e[i]), int(b_e[j]))
        if hi > lo:
            total += hi - lo
        if a_e[i] < b_e[j]:
            i += 1
        else:
            j += 1
    return total


def any_overlap(query_s: np.ndarray, query_e: np.ndarray, ref_s: np.ndarray, ref_e: np.ndarray) -> np.ndarray:
    """For each closed query interval: does it overlap any interval of a merged reference list?"""
    if len(ref_s) == 0:
        return np.zeros(len(query_s), dtype=bool)
    idx = np.searchsorted(ref_s, query_e, side="right") - 1
    ok = idx >= 0
    out = np.zeros(len(query_s), dtype=bool)
    out[ok] = ref_e[idx[ok]] >= query_s[ok]
    return out


def vor_corrected_event_wise(alarm_s: np.ndarray, alarm_e: np.ndarray, event_segments: list[list[tuple[int, int]]],
                             include: np.ndarray, all_event_s: np.ndarray, all_event_e: np.ndarray,
                             t0: int, t1: int, beta: float = 0.5) -> dict:
    """VOR Eq. 1-2 in the time domain.

    alarm_s/e: alarm spans (sorted, disjoint); event_segments: per scoreable event its closed segments;
    include: which scoreable events are counted (TP/FN); all_event_s/e: every test event segment of any
    event category (any channel) - their union defines non-nominal time and FP status.
    """
    a_s, a_e = merge_intervals(alarm_s, alarm_e)
    u_s, u_e = merge_intervals(all_event_s, all_event_e)
    u_s, u_e = clip_intervals(u_s, u_e, t0, t1)
    tp = fn = 0
    for segs, inc in zip(event_segments, include):
        if not inc:
            continue
        ss = np.asarray([x[0] for x in segs], dtype=np.int64)
        ee = np.asarray([x[1] for x in segs], dtype=np.int64)
        hit = bool(any_overlap(ss, ee, a_s, a_e).any()) if len(a_s) else False
        tp += int(hit)
        fn += int(not hit)
    raw_s = np.asarray(alarm_s, dtype=np.int64)
    raw_e = np.asarray(alarm_e, dtype=np.int64)
    fp = int((~any_overlap(raw_s, raw_e, u_s, u_e)).sum()) if len(raw_s) else 0
    ca_s, ca_e = clip_intervals(a_s, a_e, t0, t1)
    alarm_len = int((ca_e - ca_s).sum())
    fpt = alarm_len - intersection_length(ca_s, ca_e, u_s, u_e)
    nt = (t1 - t0) - int((u_e - u_s).sum())
    pre = (tp / (tp + fp)) * (1.0 - fpt / nt) if (tp + fp) > 0 and nt > 0 else float("nan")
    rec = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    if not (np.isfinite(pre) and np.isfinite(rec)) or (beta ** 2 * pre + rec) == 0:
        f = float("nan") if not (np.isfinite(pre) and np.isfinite(rec)) else 0.0
    else:
        f = (1 + beta ** 2) * pre * rec / (beta ** 2 * pre + rec)
    return {"TPe": tp, "FNe": fn, "FPe": fp, "FPt_s": fpt / 1e9, "Nt_s": nt / 1e9, "Pre": pre, "Rece": rec,
            "F0.5e": f}

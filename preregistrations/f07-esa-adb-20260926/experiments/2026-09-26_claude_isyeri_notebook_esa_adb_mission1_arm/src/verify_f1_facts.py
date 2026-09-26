"""Editor-side independent recount of the factual claims in the F1 review (label structure only).

Operation: f07-rb4-esa-adb-revision-20260926
Two-source rule: every F1 factual claim that changes the protocol is recounted here from the
F3 tables with a separate implementation before it is adopted. Reads only f3_schema CSVs (no
archive, no model, no score). Writes f1_review/EDITOR_FACT_CHECK.json.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

RUN = Path(__file__).resolve().parents[1]
F3 = RUN / "f3_schema"
TEST = pd.Timestamp("2007-01-01T00:00:00")
DRIFT = pd.Timestamp("2012-07-01T00:00:00")
STEP_S, SPAN_S = 150.0, 570.0

labels = pd.read_csv(F3 / "meta_labels.csv")
types = pd.read_csv(F3 / "meta_anomaly_types.csv")
chans = pd.read_csv(F3 / "meta_channels.csv")
labels["S"] = pd.to_datetime(labels["StartTime"], utc=True).dt.tz_localize(None)
labels["E"] = pd.to_datetime(labels["EndTime"], utc=True).dt.tz_localize(None)
lab = labels.merge(types[["ID", "Category", "Class"]], on="ID", how="left")
assert lab["Category"].notna().all()
target = set(chans.loc[chans["Target"] == "YES", "Channel"])
assert len(target) == 58, len(target)
light = {f"channel_{i}" for i in range(41, 47)}
group = dict(zip(chans["Channel"], chans["Group"]))

ev = lab[lab["Category"].isin(["Anomaly", "Rare Event"])]
gaps = lab[lab["Category"] == "Communication Gap"]
rows = []
for eid, g in ev.groupby("ID"):
    s, e = g["S"].min(), g["E"].max()
    aff = set(g["Channel"]) & target
    rows.append({"ID": eid, "cat": g["Category"].iloc[0], "cls": g["Class"].iloc[0], "S": s, "E": e,
                 "m": len(aff), "aff": aff, "m_light": len(set(g["Channel"]) & light),
                 "segs": list(zip(g["S"], g["E"]))})
evt = pd.DataFrame(rows)
test = evt[evt["S"] >= TEST].reset_index(drop=True)
out = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "tool": "Cowork-Claude",
       "model": "claude-opus-5-5 (editor)", "operation_id": "f07-rb4-esa-adb-revision-20260926", "checks": {}}
ck = out["checks"]

# positive control: known F3 totals
ck["test_events"] = int(len(test))
assert len(test) == 91, len(test)
ck["events_total"] = int(len(evt))
assert len(evt) == 196, len(evt)

dur_h = (test["E"] - test["S"]).dt.total_seconds() / 3600.0
ck["test_duration_h"] = {"median": round(float(dur_h.median()), 2), "p75": round(float(dur_h.quantile(0.75)), 2),
                         "n_ge_24h": int((dur_h >= 24).sum()), "n_ge_7d": int((dur_h >= 24 * 7).sum())}

# overlapping-window count per event: windows [ws, ws+570 s] on a 150 s step overlapping any segment
def n_windows(segs):
    idx = set()
    for s, e in segs:
        s0 = (s - TEST).total_seconds()
        e0 = (e - TEST).total_seconds()
        lo = math.ceil((s0 - SPAN_S) / STEP_S)
        hi = math.floor(e0 / STEP_S)
        idx.update(range(lo, hi + 1))
    return len(idx)

nw = np.array([n_windows(sg) for sg in test["segs"]])
chance = {}
for p in (0.005, 0.01, 0.05, 0.20):
    pd_ = 1 - (1 - p) ** nw
    chance[str(p)] = {"expected_detected": round(float(pd_.sum()), 1), "n_prob_gt_0_95": int((pd_ > 0.95).sum())}
ck["bernoulli_chance_detection"] = chance
ck["overlapping_windows"] = {"median": int(np.median(nw)), "min": int(nw.min()), "max": int(nw.max())}

lt = test[test["m_light"] > 0]
ck["lightweight"] = {"events": int(len(lt)), "m_eq_6": int((lt["m_light"] == 6).sum()),
                     "partial": sorted(f"{r.ID}:{r.m_light}" for r in lt.itertuples() if 0 < r.m_light < 6)}

ck["drift_era"] = {"start_ge_2012_07_01": int((test["S"] >= DRIFT).sum()),
                   "by_year": {str(k): int(v) for k, v in test["S"].dt.year.value_counts().sort_index().items()}}
three = test[(test["m"] == 3) & (test["cat"] == "Anomaly")]
trio = {"channel_14", "channel_21", "channel_29"}
ck["three_channel_test_anomalies"] = {"n": int(len(three)), "on_14_21_29": int(sum(1 for a in three["aff"] if a == trio)),
                                      "groups_of_trio": sorted({int(group[c]) for c in trio})}
ck["affected_set_size"] = {"median": float(test["m"].median()), "n_m_eq_58": int((test["m"] == 58).sum())}

C = 58
ev_ok = test[(test["m"] > 0) & (test["m"] < C)]
def hit3(m):
    return 1.0 - math.comb(C - m, 3) / math.comb(C, 3) if C - m >= 3 else 1.0
ck["chance_hit3"] = {"n_events": int(len(ev_ok)), "mean": round(float(np.mean([hit3(m) for m in ev_ok["m"]])), 3),
                     "at_m_12": round(hit3(12), 3)}

pairs = []
for (i, a), (j, b) in combinations(test.iterrows(), 2):
    if a["S"] <= b["E"] and b["S"] <= a["E"]:
        pairs.append(f"{a['ID']}~{b['ID']}")
ck["overlapping_test_event_pairs"] = {"n": len(pairs), "pairs": pairs}
ck["gaps"] = {"n": int(gaps["ID"].nunique()), "in_test": int((gaps["S"] >= TEST).sum()),
              "latest_end": str(gaps["E"].max())}
ck["classes_test"] = {str(k): int(v) for k, v in test["cls"].value_counts().items()}
(RUN / "f1_review").mkdir(exist_ok=True)
(RUN / "f1_review" / "EDITOR_FACT_CHECK.json").write_bytes(json.dumps(out, indent=1, default=str).encode("utf-8"))
print(json.dumps(out, indent=1, default=str))

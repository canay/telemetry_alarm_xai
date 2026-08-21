"""Resumable work units: feat:<seed> | model:<seed>:<name> | cross:<seed>.
Each unit writes a checkpoint under ../ckpt and is idempotent."""
import sys, os, json, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (W, STRIDE, NCH, window_features, window_labels,
                    windows_of_event, event_metrics, ndcg_at_k,
                    topk_jaccard, spearman)
import models as M

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CKPT = os.path.join(BASE, "ckpt")
DATA = os.path.join(BASE, "data")
N_REP = 3
TOPK = 3


def unit_feat(seed):
    out = f"{CKPT}/feat_seed{seed}.npz"
    if os.path.exists(out):
        return
    d = np.load(f"{DATA}/telemetry_seed{seed}.npz")
    res = {}
    for part in ["Xtr", "Xval", "Xtl", "Xte"]:
        F, S = window_features(d[part])
        res[part + "_F"], res[part + "_S"] = F, S
    mu, sd = res["Xtr_F"].mean(0), res["Xtr_F"].std(0) + 1e-9
    for part in ["Xtr", "Xval", "Xtl", "Xte"]:
        res[part + "_F"] = (res[part + "_F"] - mu) / sd
    res["ytl_w"] = window_labels(res["Xtl_S"], d["ytl"])
    res["yte_w"] = window_labels(res["Xte_S"], d["yte"])
    np.savez_compressed(out, **res)


def _load(seed):
    f = np.load(f"{CKPT}/feat_seed{seed}.npz")
    d = np.load(f"{DATA}/telemetry_seed{seed}.npz")
    ev = json.loads(str(d["ev_te"]))
    return f, ev


def unit_model(seed, name):
    outj = f"{CKPT}/model_seed{seed}_{name}.json"
    if os.path.exists(outj):
        return
    t0 = time.time()
    f, events = _load(seed)
    Ztr, Zval, Ztl, Zte = f["Xtr_F"], f["Xval_F"], f["Xtl_F"], f["Xte_F"]
    Ste, ytl, yte = f["Xte_S"], f["ytl_w"], f["yte_w"]
    rng = np.random.default_rng(seed * 97 + 13)

    reps, sc_te, sc_val = [], [], []
    for r in range(N_REP):
        m = M.fit_model(name, 100 * seed + r, Ztr, Ztl, ytl)
        reps.append(m)
        sc_te.append(M.score(name, m, Zte))
        sc_val.append(M.score(name, m, Zval))
    sc_te, sc_val = np.array(sc_te), np.array(sc_val)
    ms_te, ms_val = sc_te.mean(0), sc_val.mean(0)
    thr = np.quantile(ms_val, 0.99)

    from sklearn.metrics import roc_auc_score, average_precision_score
    auroc = float(roc_auc_score(yte, ms_te))
    ap = float(average_precision_score(yte, ms_te))
    em = event_metrics(ms_te, thr, Ste, events, len(Ste))

    # per-type window AUROC and event recall
    per_type = {}
    nominal = yte == 0
    for typ in set(e["type"] for e in events):
        wi = np.concatenate([windows_of_event(Ste, e) for e in events
                             if e["type"] == typ])
        mask = nominal.copy()
        mask[wi] = True
        yt = np.zeros(len(yte), int)
        yt[wi] = 1
        per_type[typ] = dict(
            auroc=float(roc_auc_score(yt[mask], ms_te[mask])),
            rec_ev=float(np.mean([em["detected"][k] for k, e in
                                  enumerate(events) if e["type"] == typ])))

    # attributions on detected events (peak window per event), per replicate
    det_idx = [k for k, d_ in enumerate(em["detected"]) if d_]
    peak = {}
    for k in det_idx:
        wi = windows_of_event(Ste, events[k])
        peak[k] = int(wi[np.argmax(ms_te[wi])])
    att_nat = np.full((N_REP, len(events), NCH), np.nan)
    att_occ = np.full((N_REP, len(events), NCH), np.nan)
    if det_idx:
        Zq = Zte[[peak[k] for k in det_idx]]
        for r, m in enumerate(reps):
            att_nat[r, det_idx] = M.native_attr(name, m, Zq, Ztr)
            att_occ[r, det_idx] = M.occlusion_attr(name, m, Zq, Ztr, rng)

    def attr_eval(att):
        ev_rows = []
        for k in det_idx:
            e = events[k]
            a = np.nanmean(att[:, k], 0)
            order = np.argsort(a)[::-1]
            rank = int(np.where(order == e["ch"])[0][0]) + 1
            ok_set = {e["ch"]} | ({e["sec"]} if e["sec"] >= 0 else set())
            hit1 = int(order[0] in ok_set)
            hit3 = int(len(ok_set & set(order[:TOPK])) > 0)
            jac = np.mean([topk_jaccard(att[i, k], att[j, k], TOPK)
                           for i in range(N_REP) for j in range(i + 1, N_REP)])
            rho = np.mean([spearman(att[i, k], att[j, k])
                           for i in range(N_REP) for j in range(i + 1, N_REP)])
            conc = float(a[order[0]] / (a.sum() + 1e-12))
            ev_rows.append(dict(k=k, type=e["type"], mode=e["mode"],
                                sev=e["sev"], rank=rank, hit1=hit1, hit3=hit3,
                                jaccard=float(jac), spearman=float(rho),
                                conc=conc))
        return ev_rows

    rows_nat, rows_occ = attr_eval(att_nat), attr_eval(att_occ)

    # alarm prioritization over episodes
    eps = em["episodes"]
    ep_rows = []
    if eps:
        pk = [a + int(np.argmax(ms_te[a:b + 1])) for a, b in eps]
        Zq = Zte[pk]
        att_ep = np.stack([M.native_attr(name, m, Zq, Ztr) for m in reps])
        vmu, vsd = ms_val.mean(), ms_val.std() + 1e-12
        for i, (a, b) in enumerate(eps):
            rel = 0
            for e in events:
                wi = windows_of_event(Ste, e)
                if len(wi) and (wi >= a).any() and (wi <= b).any() and \
                   len(set(range(a, b + 1)) & set(wi.tolist())):
                    rel = max(rel, e["sev"])
            am = att_ep[:, i].mean(0)
            jac = np.mean([topk_jaccard(att_ep[r1, i], att_ep[r2, i], TOPK)
                           for r1 in range(N_REP)
                           for r2 in range(r1 + 1, N_REP)])
            ep_rows.append(dict(rel=int(rel),
                                score=float((ms_te[pk[i]] - vmu) / vsd),
                                stab=float(jac),
                                conc=float(am.max() / (am.sum() + 1e-12))))

    def rank_metrics(keyvals):
        order = np.argsort(-np.asarray(keyvals))
        rels = [ep_rows[i]["rel"] for i in order]
        return dict(ndcg10=float(ndcg_at_k(rels, 10)),
                    p5_hisev=float(np.mean([r == 3 for r in rels[:5]])) if len(rels) >= 1 else 0.0)

    prio = {}
    if ep_rows:
        sc = np.array([r["score"] for r in ep_rows])
        st = np.array([r["stab"] for r in ep_rows])
        co = np.array([r["conc"] for r in ep_rows])
        z = lambda v: (v - v.mean()) / (v.std() + 1e-12)
        prio["baseline"] = rank_metrics(sc)
        prio["aware_add"] = rank_metrics(z(sc) + z(st) + z(co))
        prio["aware_mult"] = rank_metrics((sc - sc.min() + 1e-6) * (0.5 + st))

    np.savez_compressed(f"{CKPT}/model_seed{seed}_{name}.npz",
                        att_nat=att_nat, att_occ=att_occ,
                        det=np.array(em["detected"]), ms_te=ms_te, thr=thr)
    res = dict(seed=seed, model=name, family=M.FAMILY[name], auroc=auroc,
               ap=ap, prec_ev=em["prec_ev"], rec_ev=em["rec_ev"],
               f1_ev=em["f1_ev"], f1_pa=em["f1_pa"], n_episodes=em["n_episodes"],
               n_detected=len(det_idx), per_type=per_type,
               attr_native=rows_nat, attr_occl=rows_occ,
               episodes=ep_rows, prio=prio, runtime=time.time() - t0)
    with open(outj, "w") as fh:
        json.dump(res, fh)


def unit_cross(seed):
    out = f"{CKPT}/cross_seed{seed}.json"
    if os.path.exists(out):
        return
    atts, dets = {}, {}
    for name in M.MODELS:
        z = np.load(f"{CKPT}/model_seed{seed}_{name}.npz")
        atts[name] = np.nanmean(z["att_nat"], 0)
        dets[name] = z["det"]
    pairs = {}
    for i, a in enumerate(M.MODELS):
        for b in M.MODELS[i + 1:]:
            both = dets[a] & dets[b]
            ks = np.where(both)[0]
            if len(ks) == 0:
                pairs[f"{a}|{b}"] = None
                continue
            jac = [topk_jaccard(atts[a][k], atts[b][k], TOPK) for k in ks]
            pairs[f"{a}|{b}"] = dict(jaccard=float(np.mean(jac)), n=int(len(ks)))
    with open(out, "w") as fh:
        json.dump(dict(seed=seed, pairs=pairs), fh)


if __name__ == "__main__":
    parts = sys.argv[1].split(":")
    if parts[0] == "feat":
        unit_feat(int(parts[1]))
    elif parts[0] == "model":
        unit_model(int(parts[1]), parts[2])
    elif parts[0] == "cross":
        unit_cross(int(parts[1]))
    print("DONE", sys.argv[1])

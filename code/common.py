"""Shared windowing, models, attribution, and metric utilities."""
import numpy as np, json

W, STRIDE = 20, 5
NCH = 12
NFEAT_PER_CH = 4  # mean, std, slope, delta

def window_features(X):
    n = X.shape[0]
    starts = np.arange(0, n - W + 1, STRIDE)
    t = np.arange(W) - (W-1)/2.0
    denom = (t**2).sum()
    feats = np.empty((len(starts), NCH*NFEAT_PER_CH), dtype=np.float64)
    for i, st in enumerate(starts):
        seg = X[st:st+W]
        mu = seg.mean(0); sd = seg.std(0)
        slope = (t[:,None]*(seg-mu)).sum(0)/denom
        delta = seg[-1]-seg[0]
        feats[i] = np.concatenate([mu, sd, slope, delta])
    return feats, starts

def feat_to_channel(att_feat):
    """Aggregate |attribution| over the 4 features of each channel."""
    # layout: [mu(12), sd(12), slope(12), delta(12)]
    A = np.abs(att_feat).reshape(NFEAT_PER_CH, NCH)
    return A.sum(0)

def window_labels(starts, y):
    lab = np.array([int(y[st:st+W].any()) for st in starts])
    return lab

def windows_of_event(starts, ev):
    return np.where((starts < ev["end"]) & (starts + W > ev["start"]))[0]

def event_metrics(scores, thr, starts, events, n_samples):
    """Event-wise + point-adjusted window metrics.
    Event recall: event detected iff >=1 overlapping window has score>thr.
    Episode precision: maximal runs of consecutive flagged windows; an episode
    is a true positive iff it overlaps >=1 labeled event window-range.
    Point-adjust (Xu et al. 2018): if any window overlapping an event is
    flagged, all windows overlapping that event are set flagged; then
    window-level P/R/F1 on adjusted flags vs any-overlap window labels."""
    flag = scores > thr
    det = []
    for ev in events:
        wi = windows_of_event(starts, ev)
        det.append(bool(flag[wi].any()) if len(wi) else False)
    # episodes
    eps = []; i = 0
    while i < len(flag):
        if flag[i]:
            j = i
            while j+1 < len(flag) and flag[j+1]: j += 1
            eps.append((i,j)); i = j+1
        else: i += 1
    y_ev = np.zeros(len(flag), dtype=bool)
    for ev in events:
        y_ev[windows_of_event(starts, ev)] = True
    ep_tp = sum(1 for (a,b) in eps if y_ev[a:b+1].any())
    prec = ep_tp/len(eps) if eps else 0.0
    rec = float(np.mean(det)) if events else 0.0
    f1 = 2*prec*rec/(prec+rec) if prec+rec else 0.0
    # point-adjust
    flag_pa = flag.copy()
    for k, ev in enumerate(events):
        wi = windows_of_event(starts, ev)
        if det[k]: flag_pa[wi] = True
    tp = int((flag_pa & y_ev).sum()); fp = int((flag_pa & ~y_ev).sum())
    fn = int((~flag_pa & y_ev).sum())
    p_pa = tp/(tp+fp) if tp+fp else 0.0; r_pa = tp/(tp+fn) if tp+fn else 0.0
    f1_pa = 2*p_pa*r_pa/(p_pa+r_pa) if p_pa+r_pa else 0.0
    return dict(prec_ev=prec, rec_ev=rec, f1_ev=f1, f1_pa=f1_pa,
                p_pa=p_pa, r_pa=r_pa, n_episodes=len(eps),
                detected=[bool(d) for d in det],
                episodes=[(int(a),int(b)) for a,b in eps])

def ndcg_at_k(rels, k):
    rels = np.asarray(rels, dtype=float)
    ranked = rels[:k]
    dcg = ((2**ranked - 1)/np.log2(np.arange(2, len(ranked)+2))).sum()
    ideal = np.sort(rels)[::-1][:k]
    idcg = ((2**ideal - 1)/np.log2(np.arange(2, len(ideal)+2))).sum()
    return dcg/idcg if idcg > 0 else 0.0

def topk_jaccard(a, b, k=3):
    sa = set(np.argsort(a)[::-1][:k]); sb = set(np.argsort(b)[::-1][:k])
    return len(sa & sb)/len(sa | sb)

def spearman(a, b):
    from scipy.stats import spearmanr
    r = spearmanr(a, b).statistic
    return float(r) if np.isfinite(r) else 0.0

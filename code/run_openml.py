"""Transfer of the framework to the real OpenML 'satellite' anomaly
benchmark (data id 40900): unsupervised detectors, AUROC/AP, and
attribution stability on the top-50 ranked points (no injected-channel
ground truth exists, so correctness metrics are not defined here)."""
import json, numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sklearn.ensemble import IsolationForest
from sklearn.decomposition import PCA
from sklearn.metrics import roc_auc_score, average_precision_score
from common import topk_jaccard, spearman
from models import AE

d = np.load("../data/openml_satellite.npz")
X, y = d["X"], d["y"]
mu, sd = X.mean(0), X.std(0) + 1e-9
Z = (X - mu) / sd
N_REP = 3
out = {}
names = sys.argv[1:] if len(sys.argv) > 1 else ["iforest", "pca", "ae"]
for name in names:
    aurocs, aps, atts = [], [], []
    sc_all = []
    for r in range(N_REP):
        rng = np.random.default_rng(100 + r)
        idx = rng.choice(len(Z), len(Z), replace=True)
        if name == "iforest":
            m = IsolationForest(n_estimators=150, random_state=r).fit(Z[idx])
            sc = -m.score_samples(Z)
        elif name == "pca":
            m = PCA(n_components=10, random_state=r).fit(Z[idx])
            R = m.inverse_transform(m.transform(Z))
            sc = ((Z - R) ** 2).mean(1)
        else:
            m = AE(Z.shape[1], r).fit(Z[idx])
            sc = ((Z - m.recon(Z)) ** 2).mean(1)
        sc_all.append(sc)
        aurocs.append(roc_auc_score(y, sc)); aps.append(average_precision_score(y, sc))
        # feature attribution for this replicate on common top-50 set below
        atts.append((m, sc))
    top = np.argsort(-np.mean(sc_all, 0))[:50]
    A = []
    for m, sc in atts:
        if name == "iforest":
            import shap
            ex = shap.TreeExplainer(m, feature_perturbation="tree_path_dependent")
            sv = ex.shap_values(Z[top], check_additivity=False)
            A.append(np.abs(sv))
        elif name == "pca":
            R = m.inverse_transform(m.transform(Z[top]))
            A.append((Z[top] - R) ** 2)
        else:
            A.append((Z[top] - m.recon(Z[top])) ** 2)
    jac = np.mean([[topk_jaccard(A[i][t], A[j][t], 5)
                    for i in range(N_REP) for j in range(i+1, N_REP)]
                   for t in range(50)])
    rho = np.mean([[spearman(A[i][t], A[j][t])
                    for i in range(N_REP) for j in range(i+1, N_REP)]
                   for t in range(50)])
    out[name] = dict(auroc_mean=float(np.mean(aurocs)), auroc_std=float(np.std(aurocs)),
                     ap_mean=float(np.mean(aps)), ap_std=float(np.std(aps)),
                     jaccard5=float(jac), spearman=float(rho))
    print(name, out[name])
import os
merged = {}
pf = "../results/openml_results.json"
if os.path.exists(pf):
    merged = json.load(open(pf))
merged.update(out)
json.dump(merged, open(pf, "w"), indent=1)
print("SAVED")

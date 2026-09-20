"""Six window-based detectors spanning the explainability spectrum, with
native per-alarm channel attributions and a model-agnostic occlusion
reference. All detectors output higher-is-more-anomalous scores."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import IsolationForest, HistGradientBoostingClassifier
from sklearn.decomposition import PCA
from common import NCH, NFEAT_PER_CH

MODELS = ["lr", "dtree", "iforest", "hgb", "pca", "ae"]
FAMILY = {"lr": "interpretable", "dtree": "interpretable",
          "iforest": "tree-ensemble", "hgb": "tree-ensemble",
          "pca": "reconstruction", "ae": "reconstruction"}
SUPERVISED = {"lr": True, "dtree": True, "hgb": True,
              "iforest": False, "pca": False, "ae": False}


class AE:
    def __init__(self, d, seed):
        import torch
        import torch.nn as nn
        torch.manual_seed(seed)
        self.net = nn.Sequential(nn.Linear(d, 24), nn.ReLU(), nn.Linear(24, 8),
                                 nn.ReLU(), nn.Linear(8, 24), nn.ReLU(),
                                 nn.Linear(24, d))

    def fit(self, X):
        import torch
        torch.set_num_threads(1)
        Xt = torch.tensor(X, dtype=torch.float32)
        opt = torch.optim.Adam(self.net.parameters(), lr=1e-3)
        for ep in range(60):
            perm = torch.randperm(len(Xt))
            for i in range(0, len(Xt), 256):
                b = Xt[perm[i:i + 256]]
                loss = ((self.net(b) - b) ** 2).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
        return self

    def recon(self, X):
        import torch
        with torch.no_grad():
            return self.net(torch.tensor(X, dtype=torch.float32)).numpy()


def fit_model(name, rep_seed, Ztr, Ztl, ytl):
    """Ztr: nominal train windows (standardized); Ztl/ytl: labeled windows."""
    rng = np.random.default_rng(1000 * rep_seed + 7)
    if SUPERVISED[name]:
        idx = rng.choice(len(Ztl), len(Ztl), replace=True)
        Xb, yb = Ztl[idx], ytl[idx]
        if name == "lr":
            return LogisticRegression(max_iter=2000, C=1.0).fit(Xb, yb)
        if name == "dtree":
            return DecisionTreeClassifier(max_depth=4, random_state=rep_seed).fit(Xb, yb)
        if name == "hgb":
            return HistGradientBoostingClassifier(max_iter=150, max_depth=4,
                                                  random_state=rep_seed).fit(Xb, yb)
    idx = rng.choice(len(Ztr), len(Ztr), replace=True)
    Xb = Ztr[idx]
    if name == "iforest":
        return IsolationForest(n_estimators=150, random_state=rep_seed).fit(Xb)
    if name == "pca":
        return PCA(n_components=10, random_state=rep_seed).fit(Xb)
    if name == "ae":
        return AE(Xb.shape[1], rep_seed).fit(Xb)


def score(name, model, Z):
    if SUPERVISED[name]:
        return model.predict_proba(Z)[:, 1]
    if name == "iforest":
        return -model.score_samples(Z)
    if name == "pca":
        R = model.inverse_transform(model.transform(Z))
        return ((Z - R) ** 2).mean(1)
    if name == "ae":
        return ((Z - model.recon(Z)) ** 2).mean(1)


def native_attr(name, model, Zq, Zbg):
    """Channel attribution for query windows Zq (k x d). Returns (k, NCH)."""
    if name == "lr":
        contrib = model.coef_[0][None, :] * (Zq - Zbg.mean(0)[None, :])
        return _agg(contrib)
    if name in ("dtree", "hgb", "iforest"):
        import shap
        ex = shap.TreeExplainer(model, feature_perturbation="tree_path_dependent")
        sv = ex.shap_values(Zq, check_additivity=False)
        if isinstance(sv, list):
            sv = sv[1] if len(sv) > 1 else sv[0]
        if sv.ndim == 3:
            sv = sv[:, :, 1]
        return _agg(sv)
    if name == "pca":
        R = model.inverse_transform(model.transform(Zq))
        return _agg((Zq - R) ** 2)
    if name == "ae":
        return _agg((Zq - model.recon(Zq)) ** 2)


def _agg(att):
    A = np.abs(att).reshape(att.shape[0], NFEAT_PER_CH, NCH)
    return A.sum(1)


def occlusion_attr(name, model, Zq, Zbg, rng, n_draws=8):
    """Model-agnostic reference: replace one channel's 4 features with
    nominal background draws; attribution = mean score drop."""
    k, d = Zq.shape
    base = score(name, model, Zq)
    out = np.zeros((k, NCH))
    draws = Zbg[rng.choice(len(Zbg), n_draws)]
    for ch in range(NCH):
        cols = [f * NCH + ch for f in range(NFEAT_PER_CH)]
        big = np.repeat(Zq, n_draws, axis=0)
        for j in range(n_draws):
            big[j::n_draws][:, cols] = draws[j][cols]
        s = score(name, model, big).reshape(k, n_draws)
        out[:, ch] = base - s.mean(1)
    return np.maximum(out, 0.0)

"""Candidate boundary extension of the frozen discovery evaluator.

Not a final preregistered endpoint. No fresh test data may be consumed yet.
For n>=3 and a positive reference universe, retain the legacy curve exactly.
For n<3, the 40% integer budget cannot inspect any episode: utility is zero.
For an empty reference universe, the normalized endpoint is undefined (None).
"""
import numbers
import numpy as np
from scipy.optimize import linear_sum_assignment


def _validated(values, adjacency, utilities):
    v = np.asarray(values, dtype=np.float64)
    u = np.asarray(utilities, dtype=np.float64)
    if v.ndim != 1 or u.ndim != 1 or len(v) != len(adjacency):
        raise ValueError('One-dimensional aligned arrays required')
    if not np.isfinite(v).all() or not np.isfinite(u).all() or (v < 0).any() or (u <= 0).any():
        raise ValueError('Finite nonnegative priorities and strictly positive event utilities required')
    for row in adjacency:
        if any(not isinstance(e, numbers.Integral) or isinstance(e, bool) or not 0 <= e < len(u) for e in row):
            raise ValueError('Invalid event index')
        if len(row) != len(set(row)):
            raise ValueError('Duplicate event ID within an adjacency row')
    if not np.isfinite(u.sum()):
        raise ValueError('Nonfinite total reference utility')
    return v, u


def captured(adjacency, utilities):
    events = sorted({int(e) for row in adjacency for e in row})
    if not events:
        return 0.0
    if all(len(row) <= 1 for row in adjacency):
        return float(utilities[events].sum())
    lookup = {e: j for j, e in enumerate(events)}
    matrix = np.zeros((len(adjacency), len(events)), dtype=np.float64)
    for i, row in enumerate(adjacency):
        for event in row:
            matrix[i, lookup[event]] = utilities[event]
    rr, cc = linear_sum_assignment(-matrix)
    return float(matrix[rr, cc].sum())


def evaluate(values, adjacency, utilities, tie_seed):
    values, utilities = _validated(values, adjacency, utilities)
    n = len(values)
    if len(utilities) == 0:
        return {'status': 'NO_REFERENCE_EVENTS', 'auc': None, 'curve': None, 'n_episodes': n}
    if n < 3:
        return {'status': 'VALID_ZERO_REVIEW_CAPACITY', 'auc': 0.0, 'curve': {'0.0': 0.0, '0.4': 0.0}, 'n_episodes': n}
    rng = np.random.default_rng(tie_seed)
    orders = ([np.argsort(-values, kind='stable')] if len(np.unique(values)) == n
              else [np.lexsort((rng.random(n), -values)) for _ in range(100)])
    loads = {min(n, max(1, int(np.floor(f * n)))) / n: min(n, max(1, int(np.floor(f * n))))
             for f in [.05, .1, .2, .4]}
    loads[.4] = loads[max(loads)]
    xx = np.array([0., *sorted(loads)])
    yy = np.asarray([[0., *[captured([adjacency[i] for i in order[:loads[x]]], utilities) / utilities.sum()
                            for x in sorted(loads)]] for order in orders])
    keep = xx <= .4 + 1e-12
    auc = float(np.trapezoid(yy[:, keep], xx[keep], axis=1).mean() / .4)
    return {'status': 'VALID_LEGACY_CURVE', 'auc': auc,
            'curve': {str(float(x)): float(y) for x, y in zip(xx, yy.mean(axis=0))}, 'n_episodes': n}

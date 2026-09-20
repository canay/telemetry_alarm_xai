"""Observable-only candidate policy API; no labels or counterfactual inputs.

Operation: f07-fresh-driver-preparation-20260905
Preserves the 2026-09-04 policy arithmetic, including exact floating ties.
"""
import numpy as np

POLICIES = ("score_only", "native", "occlusion", "raw_nominal_deviation",
            "feature_nominal_deviation", "permuted_occlusion")
PLATFORM = np.array([4, 2, 2, 4, 4, 2, 1, 4, 2, 4, 4, 4], dtype=np.float64)
PAYLOAD = np.array([2, 4, 1, 2, 2, 1, 4, 2, 1, 1, 1, 1], dtype=np.float64)


def policy_values(*, scores, native, occlusion, raw_nominal_deviation,
                  feature_nominal_deviation, profile, seed):
    """Reject extra fields; normalize only the genuine empty-list shape."""
    score = np.asarray(scores, dtype=np.float64)
    criticality = np.asarray(profile, dtype=np.float64)
    if score.ndim != 1 or not np.isfinite(score).all() or (score < 0).any():
        raise ValueError("Scores must be finite nonnegative one-dimensional values")
    if (criticality.shape != (12,) or not np.isfinite(criticality).all()
            or (criticality <= 0).any()):
        raise ValueError("Exactly 12 finite positive criticalities are required")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("Nonnegative integer seed required")
    matrices = {}
    for key, value in (("native", native), ("occlusion", occlusion),
                       ("raw_nominal_deviation", raw_nominal_deviation),
                       ("feature_nominal_deviation", feature_nominal_deviation)):
        mass = np.asarray(value, dtype=np.float64)
        if len(score) == 0 and mass.shape == (0,):
            mass = mass.reshape(0, 12)
        if (mass.shape != (len(score), 12) or not np.isfinite(mass).all()
                or (mass < 0).any()
                or not np.allclose(mass.sum(axis=1), 1, atol=1e-8)):
            raise ValueError(f"Invalid channel mass: {key}")
        matrices[key] = mass
    permutation = np.random.default_rng(
        np.random.SeedSequence([20260904, int(seed), 431])).permutation(12)
    matrices["permuted_occlusion"] = matrices["occlusion"][:, permutation]
    score = score + 1e-12
    result = {"score_only": score}
    for key, mass in matrices.items():
        result[key] = (score.copy() if np.ptp(criticality) == 0
                       else score * ((mass @ criticality) / criticality.mean()))
    if any(not np.isfinite(value).all() for value in result.values()):
        raise ValueError("Nonfinite policy output")
    return result

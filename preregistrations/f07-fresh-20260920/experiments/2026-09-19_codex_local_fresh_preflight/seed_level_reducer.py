"""Prospective fixed-family seed-level reducer; no data generation or fitting.

Date/time: 2026-09-20 01:56 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919; Findings: F02/F04/F15, F07-FRESH-R2-07
Accepts a complete declared result grid, never replaces or drops a seed.
No CLI reads scientific outcomes. Callers must first pass the public-freeze
and final-protocol gates; tests use explicitly synthetic in-memory rows.
"""
import math
import numpy as np
from scipy.stats import t

SEEDS = tuple(range(1000, 1040))
MODELS = ('lr', 'dtree', 'iforest', 'hgb', 'pca', 'ae')
PRIMARY = ('lr', 'iforest', 'hgb', 'pca', 'ae')
POLICIES = ('score_only', 'native', 'occlusion', 'raw_nominal_deviation',
            'feature_nominal_deviation', 'permuted_occlusion')
PROFILES = ('uniform', *(f'lambda_{i:02d}' for i in range(11)))
TARGETS = ('original_impact', 'channel_criticality_only', 'equal_event')
DIRECTIONS = {'C1': 1, 'C2': -1, 'C3': 1, 'C4': -1}
GRID_SIZE = len(SEEDS) * len(MODELS) * len(POLICIES) * len(PROFILES) * len(TARGETS)


def indexed_grid(rows):
    grid = {}
    for row in rows:
        seed = row['seed']
        if type(seed) is not int or seed not in SEEDS:
            raise ValueError('Unexpected or non-integer seed')
        key = (seed, row['model'], row['profile'], row['policy'], row['target'])
        if (key[1] not in MODELS or key[2] not in PROFILES
                or key[3] not in POLICIES or key[4] not in TARGETS or key in grid):
            raise ValueError('Unknown or duplicate result cell')
        value = row['muc_auc_0_40']
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Invalid endpoint; missing or failed cells cannot be imputed')
        grid[key] = float(value)
    if len(grid) != GRID_SIZE:
        raise ValueError(f'Incomplete grid: {len(grid)}/{GRID_SIZE}')
    return grid


def contrasts(grid, seed, models):
    def value(model, profile, policy, target):
        return grid[seed, model, profile, policy, target]

    ends = ('lambda_00', 'lambda_10')
    raw, score, occ = 'raw_nominal_deviation', 'score_only', 'occlusion'
    critical, equal = 'channel_criticality_only', 'equal_event'
    result = {}
    for cid, target, baseline in (('C1', critical, score), ('C2', equal, score), ('C3', critical, occ)):
        # Models first, then the two endpoint profiles, as declared in the candidate.
        result[cid] = float(np.mean([np.mean([value(m, p, raw, target) - value(m, p, baseline, target)
                                             for m in models]) for p in ends]))
    result['C4'] = float(np.mean([
        (value(m, ends[1], occ, critical) - value(m, ends[1], score, critical))
        - (value(m, ends[0], occ, critical) - value(m, ends[0], score, critical))
        for m in models]))
    return result


def summarize(values, direction, adjusted=True):
    x = np.asarray(values, dtype=np.float64)
    if x.shape != (40,) or not np.isfinite(x).all():
        raise ValueError('Exactly 40 finite seed-level contrasts required')
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    alpha = .05 / 4 if adjusted else .05
    margin = float(t.ppf(1 - alpha / 2, 39) * sd / np.sqrt(40))
    lower, upper = mean - margin, mean + margin
    if (direction == 1 and lower > 0) or (direction == -1 and upper < 0):
        verdict = 'EXPECTED_DIRECTION_SUPPORTED_WITHIN_PROTOCOL'
    elif (direction == 1 and upper < 0) or (direction == -1 and lower > 0):
        verdict = 'OPPOSITE_DIRECTION_SUPPORTED_WITHIN_PROTOCOL'
    else:
        verdict = 'DIRECTION_UNRESOLVED'
    if not adjusted:
        verdict = 'DESCRIPTIVE_UNADJUSTED_' + verdict
    return {'n_independent_seeds': 40, 'df': 39, 'sample_sd_ddof': 1,
            'mean': mean, 'sample_sd': sd, 'ci_level': 1 - alpha,
            'ci': [lower, upper], 'verdict': verdict,
            'practical_importance': 'NOT_ESTABLISHED_NO_SESOI',
            'seed_values': x.tolist()}


def reduce_rows(rows):
    rows = list(rows)
    grid = indexed_grid(rows)
    queues = {}
    zero_cells = 0
    for row in rows:
        key = (row['seed'], row['model'])
        n = row.get('n_episodes')
        if type(n) is not int or n < 0 or (key in queues and queues[key] != n):
            raise ValueError('Missing, invalid or inconsistent queue size')
        queues[key] = n
        expected = 'VALID_ZERO_REVIEW_CAPACITY' if n < 3 else 'VALID_LEGACY_CURVE'
        if row.get('evaluation_status') != expected or (n < 3 and row['muc_auc_0_40'] != 0):
            raise ValueError('Queue size/status/endpoint mismatch')
        zero_cells += int(n < 3)
    outputs = {}
    for label, models in [('primary_five_models', PRIMARY), ('sensitivity_all_six', MODELS),
                          *((f'descriptive_{model}', (model,)) for model in MODELS)]:
        seed_rows = [contrasts(grid, seed, models) for seed in SEEDS]
        primary = label == 'primary_five_models'
        outputs[label] = {'models': list(models),
                         'scope': 'PRIMARY_BONFERRONI_FAMILY_4' if primary else 'SECONDARY_DESCRIPTIVE_UNADJUSTED',
                         'contrasts': {cid: summarize([r[cid] for r in seed_rows], direction, primary)
                                       for cid, direction in DIRECTIONS.items()}}
    primary = outputs['primary_five_models']['contrasts']
    sensitivity = outputs['sensitivity_all_six']['contrasts']
    agreement = {}
    for cid in DIRECTIONS:
        a, b = primary[cid], sensitivity[cid]
        sign = lambda x: int(x > 0) - int(x < 0)
        agreement[cid] = {
            'same_mean_direction': sign(a['mean']) == sign(b['mean']),
            'same_direction_support_class': a['verdict'] == b['verdict'].removeprefix('DESCRIPTIVE_UNADJUSTED_'),
            'primary_verdict': a['verdict'], 'sensitivity_verdict': b['verdict'],
            'primary_ci_level': a['ci_level'], 'sensitivity_ci_level': b['ci_level']}
    queue_summary = {}
    for model in MODELS:
        counts = [queues[seed, model] for seed in SEEDS]
        queue_summary[model] = {'seed_counts': dict(zip(map(str, SEEDS), counts)),
                                'min': min(counts), 'median': float(np.median(counts)), 'max': max(counts),
                                'zero_capacity_queues': sum(n < 3 for n in counts)}
    all_expected = all(v['verdict'] == 'EXPECTED_DIRECTION_SUPPORTED_WITHIN_PROTOCOL' for v in primary.values())
    return {'status': 'COMPLETE_FIXED_GRID_REDUCED', 'rows': GRID_SIZE,
            'seed_ids': list(SEEDS), 'results': outputs,
            'sensitivity_direction_agreement': agreement,
            'sensitivity_comparison_scope': 'DESCRIPTIVE; different CI levels; no primary verdict upgrade',
            'zero_capacity_cell_count': zero_cells,
            'cell_count_scope': 'Repeated policy/profile/target cells, not independent samples',
            'n_episodes_by_model': queue_summary,
            'family_verdict': ('ALL_FOUR_EXPECTED_DIRECTIONS_SUPPORTED_WITHIN_PROTOCOL'
                               if all_expected else 'JOINT_EXPECTED_PATTERN_NOT_ESTABLISHED'),
            'operational_benefit_claim': False, 'equivalence_claim': False,
            'sample_size_extension_allowed': False}

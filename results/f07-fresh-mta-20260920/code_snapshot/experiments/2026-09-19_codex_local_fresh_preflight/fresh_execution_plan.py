"""Prospective unit/artifact inventory only: no generation, fitting or evaluation.

Date/time: 2026-09-20 00:08 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919
The legacy smoke driver admits only seed 0; it is not a 40-seed run planner.
This module cannot launch any process or consume a scientific data artifact.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.metadata
import json
import platform

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
SEEDS = tuple(range(1000, 1040))
MODELS = ('lr', 'dtree', 'iforest', 'hgb', 'pca', 'ae')
REPLICATES = tuple(range(7))
SNAPSHOT = 'experiments/2026-09-04_codex_local_fresh_validation_candidate/code_snapshot/'
CODE = [SNAPSHOT + name for name in (
    'run_criticality_unit.py', 'run_criticality_unit_v5.py', 'common.py',
    'criticality_generator.py', 'criticality_generator_v5.py',
    'telemetry_generator.py', 'models.py')]
CODE += [
    'experiments/2026-09-05_codex_local_fresh_driver/code/policy_api.py',
    'experiments/2026-09-04_codex_local_fresh_validation_candidate/code/boundary_evaluator.py',
    'experiments/2026-09-19_codex_local_fresh_preflight/producer_policy_adapter.py',
    'experiments/2026-09-19_codex_local_fresh_preflight/fresh_execution_plan.py',
]


def producer_outputs(kind, seed, model=None):
    if type(seed) is not int or seed not in SEEDS:
        raise ValueError('The prospective plan admits only fresh seeds 1000-1039')
    if kind == 'gen' and model is None:
        return [f'data/telemetry_seed{seed}.npz']
    if kind == 'feat' and model is None:
        return [f'replicates/r{r}/{part}/{name}' for r in REPLICATES
                for part, name in (('data', f'telemetry_seed{seed}.npz'),
                                   ('ckpt', f'feat_seed{seed}.npz'))]
    if kind == 'model' and model in MODELS:
        return [f'{prefix}{part}/model_seed{seed}_{model}.{extension}'
                for prefix in ('', *(f'replicates/r{r}/' for r in REPLICATES))
                for part, extension in (('raw', 'json'), ('ckpt', 'npz'))]
    if kind == 'cross' and model is None:
        return [f'raw/cross_seed{seed}.json']
    raise ValueError('Unknown producer unit identity')


def build_plan():
    """One worker, 360 producer units plus 40 proposed policy units."""
    units = []
    for seed in SEEDS:
        gen = f'gen:{seed}'
        feat = f'feat:{seed}'
        models = [f'model:{seed}:{model}' for model in MODELS]
        for kind, unit_id, needs, model in [
            ('gen', gen, [], None), ('feat', feat, [gen], None),
            *[('model', uid, [gen, feat], model) for uid, model in zip(models, MODELS)],
            ('cross', f'cross:{seed}', models, None),
        ]:
            units.append({'unit_id': unit_id, 'seed': seed, 'kind': kind,
                          'model': model, 'depends_on': needs,
                          'outputs': producer_outputs(kind, seed, model),
                          'implementation': 'immutable_existing_producer'})
        units.append({'unit_id': f'policy:{seed}', 'seed': seed, 'kind': 'policy',
                      'model': None, 'depends_on': [gen, feat, *models],
                      'outputs': [f'policy/seed{seed}/input_bundle.json',
                                  f'policy/seed{seed}/priorities.npz',
                                  f'policy/seed{seed}/results.json'],
                      'implementation': 'NOT_IMPLEMENTED_NOT_LAUNCHABLE',
                      'expected_result_rows': 6 * 12 * 6 * 3})
    seen_ids, seen_paths = set(), set()
    for unit in units:
        uid = unit['unit_id']
        if uid in seen_ids or not set(unit['depends_on']).issubset(seen_ids):
            raise ValueError('Duplicate unit, missing dependency or dependency order')
        seen_ids.add(uid)
        for output in unit['outputs']:
            if output in seen_paths or Path(output).is_absolute() or '..' in Path(output).parts:
                raise ValueError('Duplicate or unsafe output path')
            seen_paths.add(output)
    return units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    if not target.is_relative_to(HERE) or target.exists() or target.suffix != '.json':
        raise ValueError('A new JSON file inside the preparation directory is required')
    units = build_plan()
    code = {}
    for relative in CODE:
        path = PROJECT / relative
        code[relative] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                          'bytes': path.stat().st_size}
    plan = {
        'schema_version': 1, 'status': 'PROSPECTIVE_PLAN_ONLY_NOT_LAUNCHABLE',
        'at': datetime.now(timezone.utc).isoformat(), 'tool': 'Codex',
        'model': 'gpt-6-astra / xhigh', 'operation_id': 'f07-auto-preflight-20260919',
        'change_id': 'MCC-F07-FRESH-MATCHED-VALIDATION-20260904',
        'fresh_data_accessed': False, 'model_fit_executed': False,
        'seed_ids': list(SEEDS), 'worker_count': 1, 'numerical_threads': 1,
        'planned_units': len(units), 'producer_units': 360, 'policy_units': 40,
        'planned_producer_artifacts': sum(len(u['outputs']) for u in units if u['kind'] != 'policy'),
        'planned_policy_artifacts': sum(len(u['outputs']) for u in units if u['kind'] == 'policy'),
        'planned_policy_rows': sum(u.get('expected_result_rows', 0) for u in units),
        'code_sha256': code, 'units': units,
        'environment_observation_not_final_lock': {
            'python': platform.python_version(), 'os_family': platform.system(),
            'architecture': platform.machine(),
            'packages': {p: importlib.metadata.version(p) for p in (
                'numpy', 'scipy', 'scikit-learn', 'torch', 'shap', 'psutil', 'threadpoolctl')},
        },
        'resume_rule': 'Only exact binding plus artifact hash/schema verified completed checkpoints may be skipped; no existence-only reuse or rerun of completed units.',
        'remaining_before_launch': [
            'Independent candidate-review disposition and final scientific decision',
            'Fresh producer adapter entry point; the preparation adapter intentionally accepts only discovery 0-9',
            'Policy/evaluator unit, reducer and durable full supervisor implementation',
            'Final numerical runtime and BLAS/thread binding',
            'Schema-v3 candidate-review-decision-final lineage and final independent review',
            'Exact public-freeze approval and verified public record',
            'Live resource admission and bounded-liveness evidence for the actual supervisor',
        ],
    }
    # Exclusive creation and byte-oriented readback; never overwrites an earlier plan.
    payload = (json.dumps(plan, indent=2, allow_nan=False) + '\n').encode('utf-8')
    with target.open('xb') as stream:
        stream.write(payload)
    if target.read_bytes() != payload:
        raise RuntimeError('Plan write/readback mismatch')
    print(json.dumps({k: plan[k] for k in ('status', 'planned_units',
          'planned_producer_artifacts', 'planned_policy_artifacts', 'planned_policy_rows',
          'fresh_data_accessed', 'model_fit_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()

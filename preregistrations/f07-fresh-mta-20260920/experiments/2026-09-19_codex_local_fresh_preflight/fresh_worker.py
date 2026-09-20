"""Prospective units for a frozen fresh run; no action occurs on import.

Date/time: 2026-09-20 00:35 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919
Only the supervisor may launch production after final review/public-freeze.
Priority subprocess receives one observable document, never evaluation data.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
OLD = HERE.parent / '2026-09-04_codex_local_fresh_validation_candidate'
THREAD_KEYS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise RuntimeError('Output readback mismatch')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def runtime():
    import numpy as np
    import scipy
    import sklearn
    import torch
    from threadpoolctl import threadpool_info
    torch.set_num_threads(1)
    pools = [{k: row.get(k) for k in ('user_api', 'internal_api', 'num_threads', 'prefix',
                                     'version', 'threading_layer', 'architecture')}
             for row in threadpool_info()]
    if any(p['num_threads'] != 1 for p in pools):
        raise RuntimeError('Numerical thread cap not established')
    return {'python': platform.python_version(), 'os_family': platform.system(),
            'os_release': platform.release(), 'architecture': platform.machine(),
            'packages': {p: importlib.metadata.version(p) for p in
                         ('numpy', 'scipy', 'scikit-learn', 'torch', 'shap', 'psutil', 'threadpoolctl')},
            'thread_environment': {key: os.environ.get(key) for key in THREAD_KEYS},
            'torch_threads': torch.get_num_threads(), 'threadpools': pools}


def profiles():
    import numpy as np
    from policy_api import PLATFORM, PAYLOAD
    return [('uniform', -1, 0, np.ones(12))] + [
        (f'lambda_{i:02d}', i / 10, 1 if i == 0 else 2 if i == 10 else 100 + i,
         (1 - i / 10) * PLATFORM + i / 10 * PAYLOAD) for i in range(11)]


def priorities(input_path, output_path):
    import fresh_policy_artifacts as contract
    from policy_api import policy_values
    from producer_policy_adapter import observable
    policy = json.loads(input_path.read_bytes())
    contract.validate_policy(policy)
    result = {'seed': policy['seed'], 'policy_inputs_sha256': sha(input_path), 'models': {}}
    for model, episodes in policy['models'].items():
        observable_values = observable(episodes)
        result['models'][model] = [{
            'profile': label, 'lambda': lam,
            'values': {key: array.tolist() for key, array in
                       policy_values(**observable_values, profile=c, seed=policy['seed']).items()}}
            for label, lam, sid, c in profiles()]
    write_new(output_path, result)


def verify_model(root, seed, model):
    import numpy as np
    vectors = []
    hashes = []
    for rep in range(7):
        path = root / f'replicates/r{rep}/ckpt/model_seed{seed}_{model}.npz'
        with np.load(path, allow_pickle=False) as ck:
            vector = ck['mean_val']
            if vector.ndim != 1 or not np.isfinite(vector).all() or not len(vector):
                raise ValueError('Invalid nominal validation vector')
            vectors.append(vector.copy())
            hashes.append(hashlib.sha256(vector.tobytes(order='C')).hexdigest())
    if any(v.dtype != vectors[0].dtype or not np.array_equal(v, vectors[0]) for v in vectors[1:]):
        raise RuntimeError('Shared validation score vector drift')
    return {'seed': seed, 'model': model, 'status': 'VALIDATION_SCORE_VECTORS_IDENTICAL',
            'validation_score_sha256_by_replicate': hashes,
            'fitted_parameter_bit_identity_claim': False,
            'fitted_models_recomputed_with_same_fit_rng_per_test_replicate': True,
            'episode_pooling': 'separate_segmentation_then_pooled_episode_records',
            'window_score_concatenation_for_detection_metrics': True}


def policy_unit(root, seed, source_binding):
    import numpy as np
    import fresh_policy_artifacts as contract
    from fresh_producer_adapter import build_fresh_seed
    from boundary_evaluator import evaluate
    from seed_level_reducer import MODELS, POLICIES
    dependencies = [f'gen:{seed}', f'feat:{seed}', *(f'model:{seed}:{m}' for m in MODELS)]
    hashes = {}
    for unit in dependencies:
        cp = json.loads((root / 'checkpoints' / (unit.replace(':', '_') + '.json')).read_bytes())
        if cp['status'] != 'completed' or cp['binding_sha256'] != source_binding:
            raise ValueError('Policy dependency binding mismatch')
        for relative, digest in cp['outputs'].items():
            if sha(root / relative) != digest:
                raise ValueError('Policy dependency hash drift')
            hashes[relative] = digest
    bundle, evidence = build_fresh_seed(root, seed, hashes)
    policy, evaluation = contract.split_bundle(bundle, source_binding)
    folder = root / 'policy' / f'seed{seed}'
    contract.write_pair(folder, policy, evaluation)
    subprocess.run([sys.executable, str(Path(__file__)), 'priority', '--input',
                    str(folder / 'policy_inputs.json'), '--output', str(folder / 'priorities.json'),
                    '--parent-pid', str(os.getpid()), '--parent-born', str(__import__('psutil').Process().create_time())], check=True)
    produced = json.loads((folder / 'priorities.json').read_bytes())
    if produced['seed'] != seed or produced['policy_inputs_sha256'] != sha(folder / 'policy_inputs.json'):
        raise ValueError('Priority document binding mismatch')
    adjacency, impact = contract.validate_pair(policy, evaluation)
    masses = impact / impact.sum(axis=1, keepdims=True)
    rows, diagnostics = [], []
    for model in MODELS:
        cells = produced['models'][model]
        if len(cells) != 12:
            raise ValueError('Incomplete profile grid')
        for cell, (label, lam, sid, c) in zip(cells, profiles()):
            if cell['profile'] != label or set(cell['values']) != set(POLICIES):
                raise ValueError('Profile/policy grid mismatch')
            tie_seed = 20260826 + 100000 * seed + 1000 * MODELS.index(model) + sid
            utilities = {'original_impact': impact @ c, 'channel_criticality_only': masses @ c,
                         'equal_event': np.ones(len(impact))}
            for policy_name in POLICIES:
                for target, utility in utilities.items():
                    answer = evaluate(cell['values'][policy_name], adjacency[model], utility, tie_seed)
                    if answer['auc'] is None:
                        raise ValueError('Undefined endpoint in positive reference universe')
                    rows.append({'seed': seed, 'model': model, 'profile': label, 'lambda': lam,
                                 'policy': policy_name, 'target': target,
                                 'n_episodes': len(adjacency[model]), 'muc_auc_0_40': answer['auc'],
                                 'evaluation_status': answer['status'], 'curve': answer['curve']})
        diagnostics.append({'model': model, 'n_episodes': len(adjacency[model]),
                            'multi_event_episodes': sum(len(x) > 1 for x in adjacency[model]),
                            'reference_events': len(impact)})
        print(json.dumps({'phase': 'policy_evaluation', 'seed': seed, 'model': model,
                          'completed_rows': len(rows)}), flush=True)
    if len(rows) != 1296:
        raise ValueError('Incomplete seed result grid')
    write_new(folder / 'results.json', {'seed': seed, 'rows': rows, 'diagnostics': diagnostics,
              'source_artifact_sha256': evidence, 'priority_sha256': sha(folder / 'priorities.json'),
              'policy_input_sha256': sha(folder / 'policy_inputs.json'),
              'evaluation_key_sha256': sha(folder / 'evaluation_key.json')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('runtime', 'priority', 'unit'))
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--unit')
    parser.add_argument('--binding')
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--parent-born', type=float)
    args = parser.parse_args()
    if args.mode == 'priority':
        import threading
        from fresh_owned_worker import parent_alive, watch_parent
        if args.parent_pid is None or args.parent_born is None or not parent_alive(args.parent_pid, args.parent_born):
            raise RuntimeError('Priority process requires a live identified parent')
        threading.Thread(target=watch_parent, args=(args.parent_pid, args.parent_born, threading.Event()), daemon=True).start()
    for key in THREAD_KEYS:
        if os.environ.get(key) != '1':
            raise RuntimeError('Supervisor must set thread environment before Python imports')
    sys.path[:0] = [str(OLD / 'code_snapshot'), str(OLD / 'code'),
                   str(HERE.parent / '2026-09-05_codex_local_fresh_driver/code')]
    environment = runtime()
    if args.mode == 'runtime':
        if args.output is None:
            print(json.dumps(environment, sort_keys=True))
        else:
            write_new(args.output.resolve(), environment)
        return
    if args.mode == 'priority':
        priorities(args.input.resolve(), args.output.resolve())
        return
    root = args.root.resolve()
    if not root.is_relative_to(HERE) or root == HERE:
        raise ValueError('Dedicated preparation-local fresh run root required')
    manifest = json.loads((root / 'RUN_MANIFEST.json').read_bytes())
    if args.binding != manifest['binding_sha256'] or environment != manifest['binding']['runtime']:
        raise ValueError('Worker binding/runtime mismatch')
    parts = args.unit.split(':')
    if len(parts) not in (2, 3) or int(parts[1]) not in range(1000, 1040):
        raise ValueError('Invalid fresh unit')
    seed = int(parts[1])
    import run_criticality_unit_v5 as producer
    if parts[0] == 'gen' and len(parts) == 2:
        producer.unit_generate(root, seed, 1.)
    elif parts[0] == 'feat' and len(parts) == 2:
        producer.unit_features(root, seed)
    elif parts[0] == 'model' and len(parts) == 3:
        producer.unit_model(root, seed, parts[2])
        write_new(root / 'integrity' / f'model_seed{seed}_{parts[2]}.json', verify_model(root, seed, parts[2]))
    elif parts[0] == 'cross' and len(parts) == 2:
        producer.unit_cross(root, seed)
    elif parts[0] == 'policy' and len(parts) == 2:
        policy_unit(root, seed, args.binding)
    else:
        raise ValueError('Unknown fresh unit')
    print(json.dumps({'unit': args.unit, 'status': 'WORKER_COMPLETE'}), flush=True)


if __name__ == '__main__':
    main()

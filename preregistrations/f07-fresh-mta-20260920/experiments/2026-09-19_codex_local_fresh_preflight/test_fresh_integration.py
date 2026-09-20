"""Fresh code paths with explicitly synthetic bundles; no gen/fit or data reads.

Date/time: 2026-09-20 01:00 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919; findings RT01/RT04/RT05
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
sys.path[:0] = [str(HERE.parent / '2026-09-04_codex_local_fresh_validation_candidate/code'),
               str(HERE.parent / '2026-09-05_codex_local_fresh_driver/code')]
import fresh_worker as worker
import fresh_policy_artifacts as contract
import fresh_producer_adapter as adapter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not args.output.replace('_', '').isalnum():
        raise ValueError('Simple new fixture directory required')
    root = HERE / args.output
    root.mkdir(exist_ok=False)
    binding = 'a' * 64
    models = contract.MODELS
    bundle = {'seed': 1000, 'evaluation_event_impact': [[1.] * 12 for _ in range(252)],
              'policy_episodes': {m: [dict(episode_uid=f's1000:r0:e{i}', score_tail_surprisal=float(i + 1),
                  event_ids=[i], **{key: [1 / 12] * 12 for key in contract.MASS_KEYS})
                  for i in range(j)] for j, m in enumerate(models)}}
    for uid in ['gen:1000', 'feat:1000', *(f'model:1000:{m}' for m in models)]:
        worker.write_new(root / 'checkpoints' / (uid.replace(':', '_') + '.json'),
                         {'status': 'completed', 'binding_sha256': binding, 'outputs': {}})
    checks = []
    # Inject only the producer adapter boundary. The policy subprocess, split,
    # UID join, evaluator and 1296-cell grid writer are the actual fresh code.
    with patch.object(adapter, 'build_fresh_seed', return_value=(deepcopy(bundle), {})) as mock:
        worker.policy_unit(root, 1000, binding)
        mock.assert_called_once_with(root, 1000, {})
    checks.append('actual_policy_unit_nested_path_and_subprocess')
    folder = root / 'policy/seed1000'
    doc = json.loads((folder / 'results.json').read_bytes())
    assert len(doc['rows']) == 1296
    checks.append('complete_synthetic_policy_grid')
    for j, model in enumerate(models):
        rows = [row for row in doc['rows'] if row['model'] == model]
        assert all(row['n_episodes'] == j for row in rows)
        assert all(isinstance(row['curve'], dict) and row['curve']['0.0'] == 0. for row in rows)
        if j < 3:
            assert all(row['muc_auc_0_40'] == 0 and row['evaluation_status'] == 'VALID_ZERO_REVIEW_CAPACITY' for row in rows)
            assert all(row['curve'] == {'0.0': 0., '0.4': 0.} for row in rows)
        else:
            assert all(0 < row['muc_auc_0_40'] < 1 for row in rows)
        checks.append('known_small_queue_' + str(j))
    policy = json.loads((folder / 'policy_inputs.json').read_bytes())
    evaluation = json.loads((folder / 'evaluation_key.json').read_bytes())
    contract.validate_pair(policy, evaluation)
    assert 'event_ids' not in json.dumps(policy) and 'event_impact' not in policy
    checks.append('observable_only_serialized_policy')
    bad = deepcopy(policy)
    bad['models']['dtree'][0]['event_ids'] = [0]
    worker.write_new(root / 'bad_policy.json', bad)
    try:
        worker.priorities(root / 'bad_policy.json', root / 'forbidden_priorities.json')
    except ValueError:
        assert not (root / 'forbidden_priorities.json').exists()
        checks.append('actual_priority_entry_rejects_evaluation_field')
    else:
        raise AssertionError('Evaluation field accepted')
    for bad_seed in (0, 999, 1040, True):
        bad = deepcopy(policy)
        bad['seed'] = bad_seed
        try:
            contract.validate_policy(bad)
        except ValueError:
            checks.append('fresh_contract_rejects_seed_' + str(bad_seed))
        else:
            raise AssertionError('Invalid fresh seed accepted')
    report = {'status': 'PASS_SYNTHETIC_FRESH_POLICY_INTEGRATION_ONLY', 'checks': checks,
              'count': len(checks), 'at': datetime.now(timezone.utc).isoformat(),
              'tool': 'Codex', 'model': 'gpt-6-astra / xhigh', 'operation_id': 'f07-auto-preflight-20260919',
              'scientific_data_read': False, 'model_fit_executed': False,
              'boundary': 'adapter mock; actual policy subprocess/evaluator; no OS sandbox claim',
              'code_sha256': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                 for name in ('fresh_worker.py', 'fresh_policy_artifacts.py', 'fresh_owned_worker.py', Path(__file__).name)}}
    worker.write_new(root / 'REPORT.json', report)
    print(json.dumps({'status': report['status'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()

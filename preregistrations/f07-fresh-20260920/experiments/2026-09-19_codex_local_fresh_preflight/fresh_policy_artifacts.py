"""Prospective fresh-run separation; launch permission belongs to the supervisor.

Date/time: 2026-09-20 00:35 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919; Finding: F05
No scientific producer, fitting, file reader, or policy implementation is run.
The policy worker receives only the policy document. This is an application
information-flow boundary, not an operating-system filesystem sandbox.
"""
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
import numpy as np

MODELS = ('lr', 'dtree', 'iforest', 'hgb', 'pca', 'ae')
MASS_KEYS = ('native_mass', 'occlusion_mass', 'raw_nominal_deviation',
             'feature_nominal_deviation')
POLICY_FIELDS = frozenset(('episode_uid', 'score_tail_surprisal', *MASS_KEYS))
HEADER = frozenset(('schema_version', 'role', 'seed', 'source_binding', 'models'))


def digest_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


def _header(doc, role, extra=()):
    if (set(doc) != HEADER | set(extra) or type(doc['schema_version']) is not int
            or doc['schema_version'] != 1 or doc['role'] != role):
        raise ValueError('Document schema or role mismatch')
    if type(doc['seed']) is not int or doc['seed'] not in range(1000, 1040):
        raise ValueError('Fresh documents accept only seeds 1000-1039')
    if not isinstance(doc['source_binding'], str) or not re.fullmatch('[0-9a-f]{64}', doc['source_binding']):
        raise ValueError('Invalid source binding')
    if set(doc['models']) != set(MODELS):
        raise ValueError('Incomplete model set')


def _uid(value, seed):
    if not isinstance(value, str) or not re.fullmatch(rf's{seed}:r[0-6]:e(?:0|[1-9][0-9]*)', value):
        raise ValueError('Invalid episode UID')


def validate_policy(doc):
    """Reject evaluation fields at every accepted policy-document level."""
    _header(doc, 'policy_inputs')
    for rows in doc['models'].values():
        if not isinstance(rows, list):
            raise ValueError('Policy rows must be a list')
        seen = set()
        for row in rows:
            if set(row) != POLICY_FIELDS:
                raise ValueError('Non-observable policy field')
            uid = row['episode_uid']
            _uid(uid, doc['seed'])
            if uid in seen:
                raise ValueError('Duplicate policy UID')
            seen.add(uid)
            score = row['score_tail_surprisal']
            if type(score) not in (int, float) or not np.isfinite(score) or score < 0:
                raise ValueError('Invalid policy score')
            for key in MASS_KEYS:
                mass = np.asarray(row[key], dtype=np.float64)
                if (mass.shape != (12,) or not np.isfinite(mass).all()
                        or (mass < 0).any() or not np.isclose(mass.sum(), 1, atol=1e-8)):
                    raise ValueError('Invalid observable mass')
    return doc


def validate_pair(policy, evaluation):
    """Evaluator-only join. UID sets, not row positions, must match per model."""
    validate_policy(policy)
    _header(evaluation, 'evaluation_key', ('event_impact', 'policy_inputs_sha256'))
    for field in ('seed', 'source_binding'):
        if policy[field] != evaluation[field]:
            raise ValueError('Policy/evaluation binding mismatch')
    if evaluation['policy_inputs_sha256'] != digest_bytes(encode(policy)):
        raise ValueError('Policy content hash mismatch')
    impact = np.asarray(evaluation['event_impact'], dtype=np.float64)
    if (impact.shape != (252, 12) or not np.isfinite(impact).all()
            or (impact < 0).any() or (impact.sum(axis=1) <= 0).any()):
        raise ValueError('Invalid evaluation universe')
    aligned = {}
    for model in MODELS:
        keyed = evaluation['models'][model]
        if not isinstance(keyed, dict):
            raise ValueError('Evaluation model must be keyed by UID')
        expected = [row['episode_uid'] for row in policy['models'][model]]
        if set(keyed) != set(expected):
            raise ValueError('Policy/evaluation UID mismatch')
        for uid, ids in keyed.items():
            _uid(uid, policy['seed'])
            if (not isinstance(ids, list) or any(type(i) is not int or not 0 <= i < 252 for i in ids)
                    or len(set(ids)) != len(ids)):
                raise ValueError('Invalid evaluation event IDs')
        aligned[model] = [keyed[uid] for uid in expected]
    return aligned, impact


def split_bundle(bundle, source_binding):
    """Run only in the preparation/export process, never the policy worker."""
    if set(bundle) != {'seed', 'policy_episodes', 'evaluation_event_impact'}:
        raise ValueError('Unexpected legacy bundle fields')
    policy = {'schema_version': 1, 'role': 'policy_inputs', 'seed': bundle['seed'],
              'source_binding': source_binding, 'models': {}}
    evaluation = {'schema_version': 1, 'role': 'evaluation_key', 'seed': bundle['seed'],
                  'source_binding': source_binding, 'models': {},
                  'event_impact': deepcopy(bundle['evaluation_event_impact'])}
    if set(bundle['policy_episodes']) != set(MODELS):
        raise ValueError('Incomplete model set')
    for model, rows in bundle['policy_episodes'].items():
        policy['models'][model], evaluation['models'][model] = [], {}
        for row in rows:
            if set(row) != POLICY_FIELDS | {'event_ids'}:
                raise ValueError('Unexpected legacy episode fields')
            uid = row['episode_uid']
            if uid in evaluation['models'][model]:
                raise ValueError('Duplicate evaluation UID')
            policy['models'][model].append({k: deepcopy(row[k]) for k in POLICY_FIELDS})
            evaluation['models'][model][uid] = deepcopy(row['event_ids'])
    validate_policy(policy)
    evaluation['policy_inputs_sha256'] = digest_bytes(encode(policy))
    validate_pair(policy, evaluation)
    return policy, evaluation


def write_pair(directory, policy, evaluation):
    """Create a new preparation-local directory; an incomplete pair has no receipt."""
    validate_pair(policy, evaluation)
    target = Path(directory).resolve()
    if not target.is_relative_to(Path(__file__).resolve().parent):
        raise ValueError('Preparation-local output required')
    target.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for filename, doc in (('policy_inputs.json', policy), ('evaluation_key.json', evaluation)):
        raw = encode(doc)
        path = target / filename
        with path.open('xb') as stream:
            stream.write(raw)
        if path.read_bytes() != raw:
            raise ValueError('Artifact readback mismatch')
        hashes[filename] = digest_bytes(raw)
    receipt = {'status': 'PREPARATION_PAIR_WRITTEN_NOT_LAUNCH_AUTHORIZATION',
               'seed': policy['seed'], 'sha256': hashes,
               'contract_sha256': digest_bytes(Path(__file__).read_bytes())}
    with (target / 'PAIR_MANIFEST.json').open('xb') as stream:
        stream.write(encode(receipt))
    return receipt

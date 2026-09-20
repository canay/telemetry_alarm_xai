"""Preparation-only producer adapter; no new confirmation seeds are accepted.

Date/time: 2026-09-19 23:28 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919
Preserves the frozen discovery baseline arithmetic, adding explicit validation.
The policy interface receives only the returned observable fields.
"""
from pathlib import Path
import hashlib
import json
import numbers
import numpy as np

MODELS = ('lr', 'dtree', 'iforest', 'hgb', 'pca', 'ae')
MASS_KEYS = ('native', 'occlusion', 'raw_nominal_deviation',
             'feature_nominal_deviation')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def mass(values):
    x = np.abs(np.asarray(values, dtype=np.float64))
    if x.shape[-1:] != (12,) or not np.isfinite(x).all():
        raise ValueError('Finite twelve-channel array required')
    denom = x.sum(axis=-1, keepdims=True)
    return np.divide(x, denom, out=np.full_like(x, 1 / 12), where=denom > 1e-12)


def observable_window_masses(train, test, starts, standardized_features):
    """No labels, counterfactuals or event information may enter this function."""
    train, test = np.asarray(train), np.asarray(test)
    starts, features = np.asarray(starts), np.asarray(standardized_features)
    if (train.ndim != 2 or test.ndim != 2 or train.shape[1] != 12
            or test.shape[1] != 12 or features.shape != (len(starts), 48)
            or starts.ndim != 1 or starts.dtype.kind not in 'iu'
            or (starts < 0).any() or (starts + 20 > len(test)).any()
            or not all(np.isfinite(x).all() for x in (train, test, features))
            or len(train) == 0):
        raise ValueError('Invalid observable window inputs')
    z = np.abs((test - train.mean(axis=0)) / (train.std(axis=0) + 1e-9))
    raw = np.asarray([z[int(s):int(s) + 20].mean(axis=0) for s in starts])
    if len(starts) == 0:
        raw = raw.reshape(0, 12)
    feature = np.abs(features).reshape(-1, 4, 12).sum(axis=1)
    return mass(raw), mass(feature)


def episode_baselines(episodes, indices, weights, raw_mass, feature_mass):
    indices, weights = np.asarray(indices), np.asarray(weights, dtype=np.float64)
    if indices.ndim != 1 or indices.dtype.kind not in 'iu' or weights.shape != indices.shape:
        raise ValueError('Invalid flagged-window arrays')
    if not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError('Invalid window weights')
    if raw_mass.shape != feature_mass.shape or raw_mass.shape[1:] != (12,):
        raise ValueError('Window mass shape mismatch')
    result, cursor, previous_end = {}, 0, -1
    for ep in episodes:
        first, last, eid = ep['window_start'], ep['window_end'], ep['episode_id']
        if (any(isinstance(x, bool) or not isinstance(x, numbers.Integral)
                for x in (first, last, eid)) or eid in result
                or not 0 <= first <= last < len(raw_mass) or first <= previous_end):
            raise ValueError('Invalid episode identity or interval')
        count = last - first + 1
        if not np.array_equal(indices[cursor:cursor + count], np.arange(first, last + 1)):
            raise ValueError('Flagged-window/episode mismatch')
        w = weights[cursor:cursor + count]
        if not np.isfinite(w.sum()) or w.sum() <= 0:
            raise ValueError('Invalid episode weight total')
        w = w / w.sum()
        result[eid] = {
            'raw_nominal_deviation': mass((raw_mass[first:last + 1] * w[:, None]).sum(axis=0)).tolist(),
            'feature_nominal_deviation': mass((feature_mass[first:last + 1] * w[:, None]).sum(axis=0)).tolist(),
        }
        cursor += count
        previous_end = last
    if cursor != len(indices) or cursor != len(weights):
        raise ValueError('Unused flagged-window records')
    return result


def observable(episodes):
    """Explicit allowlist: event IDs never enter the policy arguments."""
    result = {'scores': np.asarray([e['score_tail_surprisal'] for e in episodes], dtype=np.float64)}
    for key in MASS_KEYS:
        source_key = key + '_mass' if key in ('native', 'occlusion') else key
        result[key] = np.asarray([e[source_key] for e in episodes], dtype=np.float64).reshape(-1, 12)
    return result


def build_discovery_seed(source, seed, frozen_hashes):
    """Read only allowed discovery seeds; output provenance plus separated data."""
    if isinstance(seed, bool) or not isinstance(seed, int) or seed not in range(10):
        raise ValueError('Preparation accepts DISCOVERY seeds 0-9 only')
    source = Path(source).resolve()
    evidence, baseline, per_rep_counts, local_records = {}, {}, {}, {}

    def checked(relative):
        path = source / relative
        digest = sha(path)
        if digest.lower() != frozen_hashes[relative].lower():
            raise ValueError('Source hash drift: ' + relative)
        evidence[relative] = digest
        return path

    for rep in range(7):
        prefix = f'replicates/r{rep}'
        with np.load(checked(f'{prefix}/data/telemetry_seed{seed}.npz'), allow_pickle=False) as ds:
            train, test = ds['Xtr'], ds['Xte']
        with np.load(checked(f'{prefix}/ckpt/feat_seed{seed}.npz'), allow_pickle=False) as ft:
            starts, features = ft['Xte_S'], ft['Xte_F']
        raw_mass, feature_mass = observable_window_masses(train, test, starts, features)
        for model in MODELS:
            payload = json.loads(checked(f'{prefix}/raw/model_seed{seed}_{model}.json').read_text(encoding='utf-8-sig'))
            if (type(payload['seed']) is not int or payload['seed'] != seed
                    or payload['model'] != model or type(payload['n_episodes']) is not int
                    or payload['n_episodes'] != len(payload['episodes'])):
                raise ValueError('Producer JSON identity/count mismatch')
            per_rep_counts[rep, model] = len(payload['episodes'])
            with np.load(checked(f'{prefix}/ckpt/model_seed{seed}_{model}.npz'), allow_pickle=False) as ck:
                n = len(payload['episodes'])
                for key in ('episode_native_mass', 'episode_occlusion_mass'):
                    if ck[key].shape != (n, 12) or not np.isfinite(ck[key]).all():
                        raise ValueError('Producer episode mass shape/value mismatch')
                    json_key = key.removeprefix('episode_')
                    values = np.asarray([ep[json_key] for ep in payload['episodes']], dtype=np.float64).reshape(n, 12)
                    if not np.array_equal(values, ck[key]):
                        raise ValueError('JSON/checkpoint episode mass mismatch')
                local = episode_baselines(payload['episodes'], ck['flagged_window_indices'],
                                          ck['window_tail_weights'], raw_mass, feature_mass)
            for eid, value in local.items():
                baseline[rep, model, eid] = value
            for position, ep in enumerate(payload['episodes']):
                if type(ep['episode_id']) is not int or ep['episode_id'] != position:
                    raise ValueError('Noncanonical local episode identity')
                local_records[rep, model, position] = ep

    cells = {}
    for model in MODELS:
        payload = json.loads(checked(f'raw/model_seed{seed}_{model}.json').read_text(encoding='utf-8-sig'))
        if (type(payload['seed']) is not int or payload['seed'] != seed or payload['model'] != model
                or type(payload['n_episodes']) is not int
                or payload['n_episodes'] != len(payload['episodes'])
                or len(payload['episodes']) != sum(per_rep_counts[r, model] for r in range(7))):
            raise ValueError('Merged producer identity/count mismatch')
        seen, rows = set(), []
        for position, ep in enumerate(payload['episodes']):
            if (any(type(ep[k]) is not int for k in ('replicate', 'local_episode_id', 'episode_id'))
                    or not 0 <= ep['replicate'] < 7 or ep['local_episode_id'] < 0
                    or ep['episode_id'] != position
                    or ep['episode_uid'] != f"s{seed}:r{ep['replicate']}:e{ep['local_episode_id']}"):
                raise ValueError('Invalid pooled episode identity')
            identity = (ep['replicate'], model, ep['local_episode_id'])
            if identity in seen or identity not in local_records:
                raise ValueError('Duplicate or unknown pooled episode identity')
            seen.add(identity)
            local = local_records[identity]
            if any(ep[k] != local[k] for k in ('score_tail_surprisal', 'native_mass', 'occlusion_mass')):
                raise ValueError('Merged/local observable mismatch')
            if ep['event_ids'] != [36 * ep['replicate'] + e for e in local['event_ids']]:
                raise ValueError('Merged/local event identity mismatch')
            rows.append({k: ep[k] for k in ('score_tail_surprisal', 'native_mass',
                         'occlusion_mass', 'event_ids', 'episode_uid')} | baseline[identity])
        cells[model] = rows

    # These event attributes belong ONLY to evaluation, not policy construction.
    events = []
    with np.load(checked(f'data/telemetry_seed{seed}.npz'), allow_pickle=False) as ds:
        for rep in range(7):
            events.extend(json.loads(str(ds[f'ev_te_r{rep}'])))
    impact = np.asarray([e['impact_by_channel'] for e in events], dtype=np.float64)
    if impact.shape != (252, 12) or not np.isfinite(impact).all() or (impact < 0).any():
        raise ValueError('Invalid evaluation-only reference universe')
    if (impact.sum(axis=1) <= 0).any():
        raise ValueError('Reference event with zero impact')
    for rows in cells.values():
        for ep in rows:
            ids = ep['event_ids']
            if len(ids) != len(set(ids)) or any(type(e) is not int or not 0 <= e < len(events) for e in ids):
                raise ValueError('Invalid evaluation-only adjacency')
    return {'seed': seed, 'policy_episodes': cells,
            'evaluation_event_impact': impact.tolist()}, evidence

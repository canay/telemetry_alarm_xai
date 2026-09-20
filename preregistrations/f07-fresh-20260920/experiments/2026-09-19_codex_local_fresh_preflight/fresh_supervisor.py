"""Prospective durable supervisor, with a separate synthetic lifecycle fixture.

Date/time: 2026-09-20 01:50 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919
Scientific launch requires a reviewed schema-v3 contract, exact author approval,
current source/runtime hashes and an independently checked public release.
The fixture path cannot invoke a scientific worker or select scientific seeds.
"""
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
import psutil

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
THREAD_KEYS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


def central_tools():
    value = os.environ.get('AKADEMIK_CENTER', '').strip()
    if not value:
        raise RuntimeError('AKADEMIK_CENTER must identify the installed author workflow')
    folder = Path(value).resolve() / 'Akis1_AnaPipeline/tools'
    if not folder.is_dir():
        raise RuntimeError('AKADEMIK_CENTER does not contain the required author workflow tools')
    return folder


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid timestamp; timezone-aware ISO-8601 required') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Invalid timestamp; timezone is required')
    return parsed


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode('utf-8')


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + ('.lock' if path.suffix == '.lock' else '.tmp'))
    raw = canonical(value) + b'\n'
    with temporary.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if path.read_bytes() != raw:
        raise RuntimeError('Atomic readback mismatch')


def relative_path(base, value):
    path = (base / value).resolve()
    if path == base.resolve() or not path.is_relative_to(base.resolve()):
        raise ValueError('Path leaves declared root')
    return path


def checked_ref(ref):
    path = relative_path(PROJECT, ref['path'])
    if sha(path) != ref['sha256']:
        raise ValueError('Bound artifact hash mismatch: ' + ref['path'])
    return path


def child_env():
    env = dict(os.environ)
    env.update({key: '1' for key in THREAD_KEYS})
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def required_source_paths():
    old = 'experiments/2026-09-04_codex_local_fresh_validation_candidate/'
    prep = str(HERE.relative_to(PROJECT)).replace(os.sep, '/') + '/'
    return {old + 'code_snapshot/' + name for name in (
        'run_criticality_unit.py', 'run_criticality_unit_v5.py', 'common.py',
        'criticality_generator.py', 'criticality_generator_v5.py', 'telemetry_generator.py', 'models.py')
    } | {old + 'code/boundary_evaluator.py',
         'experiments/2026-09-05_codex_local_fresh_driver/code/policy_api.py'
    } | {prep + name for name in ('fresh_supervisor.py', 'fresh_worker.py', 'fresh_execution_plan.py',
                                  'fresh_producer_adapter.py', 'producer_policy_adapter.py',
                                  'fresh_policy_artifacts.py', 'seed_level_reducer.py', 'fresh_owned_worker.py')}


def verify_sources(sources):
    if set(sources) != required_source_paths():
        raise ValueError('Source inventory differs from the complete runtime dependency set')
    for relative, digest in sources.items():
        if sha(relative_path(PROJECT, relative)) != digest:
            raise ValueError('Frozen code drift: ' + relative)


def launch_binding(config_path):
    config = json.loads(config_path.read_bytes())
    if (config.get('status') != 'FINAL_REVIEWED_AWAITING_EXACT_PUBLIC_FREEZE'
            or config.get('seeds') != list(range(1000, 1040))):
        raise ValueError('A final fixed-seed launch configuration is required')
    contract = checked_ref(config['freeze_contract'])
    freeze_check = subprocess.run([sys.executable, str(central_tools() / 'experiment_freeze.py'),
        str(PROJECT), '--contract', str(contract.relative_to(PROJECT)), '--phase', 'prelaunch'],
        check=True, capture_output=True, text=True, timeout=120)
    expected_pass = 'PASS experiment freeze PRELAUNCH: ' + str(contract)
    if not freeze_check.stdout.splitlines() or freeze_check.stdout.splitlines()[0] != expected_pass:
        raise ValueError('Central prelaunch output lacks the exact contract PASS record')
    approval_path = checked_ref(config['public_approval'])
    approval = json.loads(approval_path.read_bytes())
    if (approval.get('approved_by') != 'author' or approval.get('action') != 'publish_exact_preregistration'
            or approval.get('freeze_contract_sha256') != sha(contract)
            or not approval.get('verbatim_user_instruction') or not approval.get('approved_at')):
        raise ValueError('Exact author public-freeze approval is absent')
    sources = config['source_sha256']
    verify_sources(sources)
    frozen = json.loads(contract.read_bytes())
    final_document = json.loads(checked_ref(frozen['lineage']['final']).read_bytes())
    final_at, approved_at = timestamp(final_document['at']), timestamp(approval['approved_at'])
    if final_at > approved_at:
        raise ValueError('Final/approval timestamp order is invalid')
    candidate_path = checked_ref(frozen['lineage']['candidate'])
    candidate = json.loads(candidate_path.read_bytes())
    if (candidate.get('runtime_source_sha256') != sources or candidate.get('runtime') != config['runtime']
            or candidate.get('seed_ids') != config['seeds']):
        raise ValueError('Launch source/runtime/seed set differs from the independently reviewed candidate')
    public = config['public_release']
    if public['repository'] != 'canay/telemetry_alarm_xai':
        raise ValueError('Unexpected publication repository')
    tag = public['tag']
    if not tag or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in tag):
        raise ValueError('Invalid tag')
    with urllib.request.urlopen('https://api.github.com/repos/canay/telemetry_alarm_xai/releases/tags/' + tag,
                                timeout=30) as response:
        release = json.load(response)
    if release.get('draft') or release.get('prerelease') or sha(contract) not in release.get('body', ''):
        raise ValueError('Public release does not bind the exact freeze contract')
    if not release.get('published_at'):
        raise ValueError('No public publication time')
    published_at = timestamp(release['published_at'])
    if not approved_at <= published_at <= datetime.now(timezone.utc):
        raise ValueError('Approval/publication timestamp order is invalid')
    observed = subprocess.run(['git', 'ls-remote', 'https://github.com/canay/telemetry_alarm_xai.git',
                               'refs/tags/' + tag, 'refs/tags/' + tag + '^{}'],
                              check=True, capture_output=True, text=True, timeout=30).stdout.splitlines()
    refs = {line.split()[1]: line.split()[0] for line in observed}
    commit = refs.get('refs/tags/' + tag + '^{}', refs.get('refs/tags/' + tag))
    if commit != public['commit_sha']:
        raise ValueError('Public Git tag commit mismatch')
    # Compare release API and Git commit API, rather than trusting a local tag.
    with urllib.request.urlopen('https://api.github.com/repos/canay/telemetry_alarm_xai/commits/' + tag,
                                timeout=30) as response:
        api_commit = json.load(response)['sha']
    if api_commit != commit:
        raise ValueError('Public identity sources disagree')
    prefix = public['package_prefix']
    if prefix != 'preregistrations/f07-fresh-20260920/':
        raise ValueError('Unexpected public package prefix')
    # A release-body hash is only an index: verify the actual published bytes.
    remote_files = dict(sources)
    for ref in [config['freeze_contract'], *[frozen['lineage'][k] for k in ('candidate', 'review', 'decision', 'final')],
                candidate['protocol_ref'], candidate['runtime_observation_ref'],
                candidate['planned_artifacts']['unit_inventory_ref']]:
        checked_ref(ref)
        remote_files[ref['path']] = ref['sha256']
    for relative, digest in remote_files.items():
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/' for c in relative):
            raise ValueError('Unsafe public artifact path')
        url = 'https://raw.githubusercontent.com/canay/telemetry_alarm_xai/' + commit + '/' + prefix + relative
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Published artifact bytes differ from the frozen local input: ' + relative)
    result = subprocess.run([sys.executable, str(HERE / 'fresh_worker.py'), 'runtime'],
                            capture_output=True, text=True, check=True, env=child_env(), timeout=60)
    observed_runtime = json.loads(result.stdout)
    if observed_runtime != config['runtime']:
        raise ValueError('Numerical runtime drift')
    confirmatory = frozen['confirmatory_binding']
    freeze_binding = {'freeze_id': frozen['freeze_id'],
        'final_sha256': frozen['lineage']['final']['sha256'],
        'decision_sha256': frozen['lineage']['decision']['sha256'],
        'threshold_id': confirmatory['threshold_id'], 'threshold_value': confirmatory['threshold_value'],
        'timebase': frozen['timebase_binding']['design_timebase']}
    return {'mode': 'FRESH_SCIENTIFIC', 'run_id': frozen['run_id'], 'freeze': freeze_binding,
            'launch_config_sha256': sha(config_path),
            'freeze_contract_sha256': sha(contract), 'source_sha256': sources,
            'runtime': observed_runtime, 'published_at': release['published_at'],
            'final_at': final_document['at'], 'approved_at': approval['approved_at'],
            'public_commit_sha': commit, 'public_approval_sha256': sha(approval_path)}


def scientific_plan():
    from fresh_execution_plan import build_plan
    units = build_plan()
    for unit in units:
        if unit['kind'] == 'model':
            unit['outputs'].append(f"integrity/model_seed{unit['seed']}_{unit['model']}.json")
        if unit['kind'] == 'policy':
            unit['outputs'] = [f"policy/seed{unit['seed']}/{name}" for name in
                               ('policy_inputs.json', 'evaluation_key.json', 'PAIR_MANIFEST.json',
                                'priorities.json', 'results.json')]
            unit['implementation'] = 'fresh_worker_policy_unit'
    return units


def checked_checkpoint(root, unit, binding_sha):
    path = root / 'checkpoints' / (unit['unit_id'].replace(':', '_') + '.json')
    if not path.exists():
        return None
    cp = json.loads(path.read_bytes())
    if (cp.get('status') != 'completed' or cp.get('unit_id') != unit['unit_id']
            or cp.get('binding_sha256') != binding_sha or set(cp['outputs']) != set(unit['outputs'])):
        raise RuntimeError('Checkpoint binding/schema mismatch')
    for name, digest in cp['outputs'].items():
        if sha(relative_path(root, name)) != digest:
            raise RuntimeError('Checkpoint output drift: ' + name)
    return cp


def schema_check(path, unit, fixture):
    if path.suffix == '.npz':
        import numpy as np
        with np.load(path, allow_pickle=False) as data:
            if not data.files:
                raise ValueError('Empty producer archive')
            for key in data.files:
                array = data[key]
                if array.dtype.kind in 'fc' and not np.isfinite(array).all():
                    raise ValueError('Nonfinite producer archive')
            if path.name.startswith('model_'):
                for name in ('episode_native_mass', 'episode_occlusion_mass'):
                    if data[name].ndim != 2 or data[name].shape[1] != 12:
                        raise ValueError('Invalid episode mass shape')
    else:
        doc = json.loads(path.read_bytes(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if fixture:
            if doc.get('unit_id') != unit['unit_id'] or doc.get('synthetic_fixture') is not True:
                raise ValueError('Fixture identity mismatch')
        elif path.name != 'PAIR_MANIFEST.json' and doc.get('seed') != unit['seed']:
            raise ValueError('Producer seed identity mismatch')
        if not fixture and path.name == 'results.json' and len(doc.get('rows', [])) != 1296:
            raise ValueError('Incomplete policy grid')
        if not fixture and path.parent.name == 'raw' and unit['kind'] == 'model':
            if (doc.get('model') != unit['model'] or type(doc.get('n_episodes')) is not int
                    or len(doc.get('episodes', [])) != doc['n_episodes']):
                raise ValueError('Model JSON identity/count mismatch')


def sample_tree(pid):
    parent = psutil.Process(pid)
    cpu, rss, pids = 0., 0, []
    for proc in [parent, *parent.children(recursive=True)]:
        try:
            timing = proc.cpu_times()
            cpu += timing.user + timing.system
            rss += proc.memory_info().rss
            pids.append(proc.pid)
        except psutil.NoSuchProcess:
            pass
    return {'process_tree_cpu_seconds': cpu, 'process_tree_rss_bytes': rss, 'sampled_pids': pids}


def stop_owned_child(child):
    try:
        parent = psutil.Process(child.pid)
        owned = [*parent.children(recursive=True), parent]
        for proc in owned:
            proc.terminate()
        _, alive = psutil.wait_procs(owned, timeout=5)
        for proc in alive:
            proc.kill()
        psutil.wait_procs(alive, timeout=5)
    except psutil.NoSuchProcess:
        pass
    child.wait(timeout=10)


@contextmanager
def runtime_mutex(root):
    """Kernel ownership survives file-content updates and is released on crash.

    Keep this file: deleting a mutex inode could let two owners lock different
    files. supervisor.lock is only the inspectable PID/launch identity record.
    """
    with (root / 'supervisor.mutex.lock').open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def checkpoint_inventory(root, units, binding_sha, fixture):
    done = []
    for unit in units:
        cp = checked_checkpoint(root, unit, binding_sha)
        if cp:
            if not set(unit['depends_on']).issubset(done):
                raise RuntimeError('Completed checkpoint has incomplete dependencies')
            for name in unit['outputs']:
                schema_check(root / name, unit, fixture)
            done.append(unit['unit_id'])
    return done


def new_manifest(root, binding, binding_sha, planned_units, fixture):
    # Use the same measured envelope writer as the canonical consumer.
    tool_folder = str(central_tools())
    if tool_folder not in sys.path:
        sys.path.insert(0, tool_folder)
    from run_manifest_writer import build_record, resolve_envelope, validate_envelope
    envelope = resolve_envelope({})
    if validate_envelope(envelope):
        raise RuntimeError('Canonical measured environment is incomplete')
    record = build_record(run_id=root.name, envelope=envelope, template={})
    if fixture:
        source_paths = (Path(__file__), HERE / 'fresh_owned_worker.py', HERE / 'supervisor_fixture_worker.py')
        sources = {p.relative_to(PROJECT).as_posix(): sha(p) for p in source_paths}
    else:
        sources = dict(binding['source_sha256'])
        verify_sources(sources)
    created = datetime.now(timezone.utc)
    if not fixture and timestamp(binding['published_at']) > created:
        raise RuntimeError('Manifest cannot precede the public preregistration')
    record.update({'created_at': created.isoformat(), 'status': 'initializing', 'snapshot_ready': False,
        'binding': binding, 'binding_sha256': binding_sha, 'planned_units': planned_units,
        'operation_id': 'f07-auto-preflight-20260919',
        'deadline_at': (created + timedelta(hours=12)).isoformat(),
        'code_snapshot': {'path': 'code_snapshot', 'source_sha256': sources},
        'code_snapshot_sha256': hashlib.sha256(canonical(sources)).hexdigest()})
    if not fixture:
        record['freeze'] = dict(binding['freeze'])
    return record


def ensure_snapshot(root, record):
    # Durable manifest intent precedes any copy. A resumed initialization keeps
    # verified copies and finishes only missing ones; temporary bytes live in
    # attempts, outside the immutable snapshot inventory.
    snapshot = relative_path(root, record['code_snapshot']['path'])
    snapshot.mkdir(exist_ok=True)
    temporary_dir = root / 'attempts' / 'snapshot_initialization'
    temporary_dir.mkdir(parents=True, exist_ok=True)
    for relative, digest in record['code_snapshot']['source_sha256'].items():
        target = relative_path(snapshot, relative)
        if target.exists():
            if sha(target) != digest:
                raise RuntimeError('Existing source snapshot byte drift: ' + relative)
            continue
        raw = relative_path(PROJECT, relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError('Source drift during snapshot construction')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = temporary_dir / (uuid.uuid4().hex + '.tmp')
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        if sha(target) != digest:
            raise RuntimeError('Source snapshot readback mismatch')
    verify_snapshot(root, record)


def verify_snapshot(root, record):
    snapshot = relative_path(root, record['code_snapshot']['path'])
    sources = record['code_snapshot']['source_sha256']
    if hashlib.sha256(canonical(sources)).hexdigest() != record['code_snapshot_sha256']:
        raise RuntimeError('Source snapshot inventory hash drift')
    actual = {p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*') if p.is_file()}
    if actual != set(sources):
        raise RuntimeError('Source snapshot file set drift')
    for relative, digest in sources.items():
        if sha(relative_path(snapshot, relative)) != digest:
            raise RuntimeError('Source snapshot byte drift: ' + relative)
    if record['binding']['mode'] == 'FRESH_SCIENTIFIC' and sources != record['binding']['source_sha256']:
        raise RuntimeError('Source snapshot differs from launch binding')


def record_status(root, manifest_path, terminal_record):
    atomic(root / 'terminal_status.json', terminal_record)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_bytes())
        manifest.update({'status': terminal_record['status'], 'last_status_at': terminal_record['at'],
                         'terminal_status_sha256': sha(root / 'terminal_status.json')})
        atomic(manifest_path, manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--fixture', action='store_true')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--stop-after', type=int, default=0)
    parser.add_argument('--recover-stale-lock', action='store_true')
    args = parser.parse_args()
    if not args.output.replace('_', '').replace('-', '').isalnum() or args.stop_after < 0:
        raise ValueError('Simple child output name and nonnegative stop count required')
    root = HERE / args.output
    if args.fixture:
        if args.config is not None:
            raise ValueError('Fixture cannot receive a scientific launch configuration')
        units = [{'unit_id': 'fixture_' + str(i), 'depends_on': ([] if i == 0 else ['fixture_0']),
                  'outputs': [f'fixture_{i}.json']} for i in range(2)]
        binding = {'mode': 'SYNTHETIC_LIFECYCLE_FIXTURE', 'supervisor_sha256': sha(Path(__file__)),
                   'worker_sha256': sha(HERE / 'supervisor_fixture_worker.py'),
                   'owned_worker_sha256': sha(HERE / 'fresh_owned_worker.py'), 'units': units}
    else:
        units = scientific_plan()
        if args.plan:
            print(json.dumps({'mode': 'PROSPECTIVE_PLAN_NOT_LAUNCH_AUTHORIZATION', 'units': len(units),
                              'artifacts': sum(len(u['outputs']) for u in units)}))
            return 0
        if args.config is None:
            raise ValueError('Exact final/public launch configuration required')
        binding = launch_binding(args.config.resolve())
        if binding['run_id'] != root.name:
            raise ValueError('Output run identity differs from the frozen protocol')
    binding_sha = hashlib.sha256(canonical(binding)).hexdigest()
    if args.plan:
        done = checkpoint_inventory(root, units, binding_sha, args.fixture)
        print(json.dumps({'mode': binding['mode'], 'preserved': done,
                          'pending': [u['unit_id'] for u in units if u['unit_id'] not in done]}))
        return 0
    root.mkdir(exist_ok=True)
    with runtime_mutex(root):
        return run_locked(args, root, units, binding, binding_sha)


def run_locked(args, root, units, binding, binding_sha):
    # RT02: authoritative inventory is measured only after kernel ownership.
    done = checkpoint_inventory(root, units, binding_sha, args.fixture)
    manifest_path = root / 'RUN_MANIFEST.json'
    if not manifest_path.exists() and any(p.name != 'supervisor.mutex.lock' for p in root.iterdir()):
        raise RuntimeError('New run root must be empty')
    if manifest_path.exists() and json.loads(manifest_path.read_bytes())['binding_sha256'] != binding_sha:
        raise RuntimeError('Manifest drift')
    lock = root / 'supervisor.lock'
    if lock.exists() and args.recover_stale_lock:
        prior_lock = json.loads(lock.read_bytes())
        if prior_lock.get('binding_sha256') != binding_sha:
            raise RuntimeError('Stale lock has a different run binding')
        try:
            old_process = psutil.Process(prior_lock['pid'])
            if old_process.create_time() == prior_lock.get('process_created_at'):
                raise RuntimeError('The locked supervisor is still alive')
        except psutil.NoSuchProcess:
            pass
        # Recover only with a recorded process creation time; PID existence alone is insufficient.
        if not isinstance(prior_lock.get('process_created_at'), (float, int)):
            raise RuntimeError('Old lock lacks process identity evidence')
        if prior_lock.get('child_pid') is not None:
            try:
                orphan = psutil.Process(prior_lock['child_pid'])
                if orphan.create_time() == prior_lock.get('child_created_at'):
                    raise RuntimeError('Recorded orphan worker is still alive; recovery refused')
            except psutil.NoSuchProcess:
                pass
        elif prior_lock.get('launch_ticket') and (root / prior_lock['launch_ticket']).exists():
            raise RuntimeError('Authorized launch lacks durable child identity')
        # A launch without a ticket cannot execute even if its wrapper starts late.
        preserved = root / 'attempts' / ('stale_lock_' + uuid.uuid4().hex + '.json')
        preserved.parent.mkdir(parents=True, exist_ok=True)
        lock.replace(preserved)
    with lock.open('x', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid(), 'process_created_at': psutil.Process().create_time(),
                   'created_at': now(), 'binding_sha256': binding_sha}, stream)
    attempt, start, child = uuid.uuid4().hex, time.monotonic(), None
    terminal, exit_code = 'FAILED', 1
    last_checkpoint_at = None
    try:
        if not manifest_path.exists():
            atomic(manifest_path, new_manifest(root, binding, binding_sha, len(units), args.fixture))
        recorded = json.loads(manifest_path.read_bytes())
        if recorded['run_id'] != root.name:
            raise RuntimeError('Manifest run identity drift')
        if not recorded['snapshot_ready']:
            ensure_snapshot(root, recorded)
            recorded['snapshot_ready'] = True
            atomic(manifest_path, recorded)
        verify_snapshot(root, recorded)
        deadline_at = datetime.fromisoformat(recorded['deadline_at'])
        if deadline_at != datetime.fromisoformat(recorded['created_at']) + timedelta(hours=12):
            raise RuntimeError('Fixed deadline binding drift')
        if datetime.now(timezone.utc) > deadline_at:
            terminal = 'RESOURCE_OR_TIMEOUT_STOP'
            raise RuntimeError('Fixed run deadline reached; restart cannot reset it')
        record_status(root, manifest_path, {'status': 'running', 'supervisor_status': 'RUNNING',
            'run_id': root.name, 'phase': 'resume_inventory_verified', 'at': now(), 'attempt_id': attempt})
        for unit in units:
            uid = unit['unit_id']
            if uid in done:
                cp = checked_checkpoint(root, unit, binding_sha)
                last_checkpoint_at = cp['completed_at']
                print(json.dumps({'unit': uid, 'status': 'SKIPPED_HASH_VERIFIED'}), flush=True)
                continue
            if args.stop_after and len(done) >= args.stop_after:
                terminal, exit_code = 'CONTROLLED_STOP', 75
                break
            if not set(unit['depends_on']).issubset(done):
                raise RuntimeError('Missing completed dependency')
            if not args.fixture:
                verify_sources(binding['source_sha256'])
                verify_snapshot(root, recorded)
            if checked_checkpoint(root, unit, binding_sha) is not None:
                raise RuntimeError('Pending unit unexpectedly acquired a completed checkpoint')
            # Recover only the pending unit's own files; completed units are immutable.
            for name in unit['outputs']:
                source = relative_path(root, name)
                if source.exists():
                    target = relative_path(root, 'attempts/' + attempt + '/previous_partial/' + name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        raise RuntimeError('Partial preservation collision')
                    source.replace(target)
            # A partial policy directory can remain, but write_pair requires a new directory.
            if not args.fixture and unit['kind'] == 'policy':
                folder = root / 'policy' / f"seed{unit['seed']}"
                if folder.exists():
                    if any(folder.iterdir()):
                        raise RuntimeError('Unexpected policy files outside declared inventory')
                    folder.rmdir()
            if not args.fixture and (shutil.disk_usage(root).free < 10 * 1024**3
                                     or psutil.virtual_memory().available < 3 * 1024**3):
                raise RuntimeError('Disk/RAM admission reserve')
            if args.fixture:
                command = [sys.executable, str(HERE / 'supervisor_fixture_worker.py'),
                           '--unit', uid, '--output', str(root / unit['outputs'][0])]
            else:
                command = [sys.executable, str(HERE / 'fresh_worker.py'), 'unit', '--root', str(root),
                           '--unit', uid, '--binding', binding_sha]
            unit_start, phase_start = time.monotonic(), now()
            log_path = root / 'logs' / (uid.replace(':', '_') + '_' + attempt + '.log')
            log_path.parent.mkdir(parents=True, exist_ok=True)
            beat_path = root / 'heartbeats' / (uid.replace(':', '_') + '_' + attempt + '.jsonl')
            beat_path.parent.mkdir(parents=True, exist_ok=True)
            record_status(root, manifest_path, {'status': 'running', 'supervisor_status': 'RUNNING',
                'run_id': root.name, 'unit': uid, 'at': now(), 'attempt_id': attempt})
            with log_path.open('xb') as log:
                launch_id = uuid.uuid4().hex
                ticket_path = root / 'attempts' / attempt / (launch_id + '.ticket.lock')
                parent_born = psutil.Process().create_time()
                intent = {'pid': os.getpid(), 'process_created_at': parent_born,
                          'binding_sha256': binding_sha, 'created_at': phase_start,
                          'launch_state': 'SPAWNING_UNAUTHORIZED', 'launch_id': launch_id,
                          'launch_ticket': str(ticket_path.relative_to(root)), 'unit_id': uid}
                atomic(lock, intent)
                wrapper_command = [sys.executable, str(HERE / 'fresh_owned_worker.py'),
                                   '--parent-pid', str(os.getpid()), '--parent-born', str(parent_born),
                                   '--ticket', str(ticket_path), '--launch-id', launch_id,
                                   '--', *command[1:]]
                log.write(canonical({'command': command, 'wrapper_command': wrapper_command, 'at': now()}) + b'\n')
                log.flush()
                child = subprocess.Popen(wrapper_command, stdout=log, stderr=subprocess.STDOUT, env=child_env())
                child_born = psutil.Process(child.pid).create_time()
                atomic(lock, intent | {'launch_state': 'CHILD_IDENTIFIED',
                                     'child_pid': child.pid, 'child_created_at': child_born})
                psutil.Process(child.pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10)
                atomic(ticket_path, {'launch_id': launch_id, 'pid': child.pid,
                                    'process_created_at': child_born, 'command': command[1:]})
                while child.poll() is None:
                    try:
                        sample = sample_tree(child.pid)
                    except psutil.NoSuchProcess:
                        break
                    beat = {'timestamp': now(), 'run_id': root.name, 'unit_id': uid, 'attempt_id': attempt,
                            'pid': child.pid, 'phase': uid.split(':')[0], 'phase_started_at': phase_start,
                            'unit_elapsed_seconds': time.monotonic() - unit_start,
                            'completed_atomic_units': len(done), 'planned_atomic_units': len(units),
                            'last_durable_checkpoint_at': last_checkpoint_at, **sample}
                    with beat_path.open('ab') as stream:
                        stream.write(canonical(beat) + b'\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                    limit = 30 if args.fixture else 900
                    if time.monotonic() - unit_start > limit or datetime.now(timezone.utc) > deadline_at:
                        terminal = 'RESOURCE_OR_TIMEOUT_STOP'
                        raise RuntimeError(terminal)
                    if not args.fixture and (sample['process_tree_rss_bytes'] > 4 * 1024**3
                            or shutil.disk_usage(root).free < 10 * 1024**3
                            or psutil.virtual_memory().available < 3 * 1024**3):
                        terminal = 'RESOURCE_OR_TIMEOUT_STOP'
                        raise RuntimeError(terminal)
                    time.sleep(.5)
                rc = child.wait()
                child = None
                log.write(canonical({'exit_code': rc, 'at': now()}) + b'\n')
                log.flush()
                os.fsync(log.fileno())
            if rc:
                raise RuntimeError('Worker failed: ' + str(rc))
            artifacts = {}
            for name in unit['outputs']:
                path = relative_path(root, name)
                schema_check(path, unit, args.fixture)
                artifacts[name] = sha(path)
            cp = {'status': 'completed', 'unit_id': uid, 'binding_sha256': binding_sha,
                  'attempt_id': attempt, 'completed_at': now(), 'outputs': artifacts,
                  'exit_code': 0, 'command': command, 'log_sha256': sha(log_path),
                  'elapsed_seconds': time.monotonic() - unit_start}
            atomic(root / 'checkpoints' / (uid.replace(':', '_') + '.json'), cp)
            last_checkpoint_at = cp['completed_at']
            done.append(uid)
            print(json.dumps({'unit': uid, 'status': 'COMPLETED'}), flush=True)
        else:
            if not args.fixture:
                from seed_level_reducer import reduce_rows
                aggregate_path = root / 'aggregate.json'
                aggregate_cp = root / 'checkpoints' / 'aggregate.json'
                if aggregate_cp.exists():
                    old = json.loads(aggregate_cp.read_bytes())
                    if old.get('binding_sha256') != binding_sha or old.get('sha256') != sha(aggregate_path):
                        raise RuntimeError('Aggregate checkpoint drift')
                    print(json.dumps({'unit': 'aggregate', 'status': 'SKIPPED_HASH_VERIFIED'}), flush=True)
                else:
                    if aggregate_path.exists():
                        saved = root / 'attempts' / attempt / 'previous_partial' / 'aggregate.json'
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        aggregate_path.replace(saved)
                    rows = []
                    for seed in range(1000, 1040):
                        rows.extend(json.loads((root / 'policy' / f'seed{seed}/results.json').read_bytes())['rows'])
                    aggregate = reduce_rows(rows)
                    atomic(aggregate_path, aggregate)
                    atomic(aggregate_cp, {'status': 'completed', 'binding_sha256': binding_sha,
                                         'sha256': sha(aggregate_path), 'completed_at': now()})
            terminal, exit_code = 'COMPLETED', 0
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            terminal, exit_code = 'CANCELLED', 130
        print(json.dumps({'status': terminal, 'error': repr(exc)}), flush=True)
    finally:
        if child is not None:
            stop_owned_child(child)
        terminal_record = {'status': terminal.lower(), 'supervisor_status': terminal,
               'run_id': root.name, 'exit_code': exit_code,
               'at': now(), 'attempt_id': attempt, 'completed_unit_ids': done,
               'elapsed_seconds': time.monotonic() - start, 'mode': binding['mode']}
        atomic(root / 'attempts' / attempt / 'terminal_status.json', terminal_record)
        record_status(root, manifest_path, terminal_record)
        lock.unlink()
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())

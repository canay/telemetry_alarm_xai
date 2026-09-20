"""Experiment-only MTA adapter for the immutable scientific supervisor.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
No central workflow is installed on the experiment node. A local central
prelaunch receipt is checked together with exact public lineage/source bytes.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
BASE = PROJECT / 'experiments/2026-09-19_codex_local_fresh_preflight'
sys.path.insert(0, str(BASE))
import fresh_supervisor as original

SELF = Path(__file__).resolve().relative_to(PROJECT).as_posix()
EXTRA = {SELF, (HERE/'mta_owned_worker.py').relative_to(PROJECT).as_posix(),
         (HERE/'mta_process_tree.py').relative_to(PROJECT).as_posix()}
ORIGINAL_VERIFY = original.verify_sources
PREFIX = 'preregistrations/f07-fresh-mta-20260920/'
REPO = 'canay/telemetry_alarm_xai'
RUN = '2026-09-20_codex_mta_fresh_internal_replication_v1'

def ref_path(ref):
    path = original.relative_path(PROJECT, ref['path'])
    if original.sha(path) != ref['sha256'] or path.stat().st_size != ref['size_bytes']:
        raise ValueError('MTA bound file mismatch: ' + ref['path'])
    return path

def read_ref(ref):
    return json.loads(ref_path(ref).read_bytes())

def verify_sources(sources):
    if set(sources) != original.required_source_paths() | EXTRA:
        raise ValueError('MTA runtime source inventory mismatch')
    ORIGINAL_VERIFY({k: v for k, v in sources.items() if k not in EXTRA})
    for path in EXTRA:
        if original.sha(PROJECT/path) != sources[path]:
            raise ValueError('MTA adapter source drift: '+path)

def remote_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)

def launch_binding(config_path):
    config = json.loads(config_path.read_bytes())
    if config.get('status') != 'FINAL_REVIEWED_PUBLIC_MTA_AMENDMENT' or config.get('seeds') != list(range(1000,1040)):
        raise ValueError('Exact prospective MTA configuration required')
    frozen = read_ref(config['freeze_contract'])
    if frozen['schema_version'] != 3 or frozen['run_id'] != RUN:
        raise ValueError('Wrong MTA freeze identity')
    lineage = frozen['lineage']
    candidate, review, decision, final = [read_ref(lineage[k]) for k in ('candidate','review','decision','final')]
    ch = lineage['candidate']['sha256']
    if (review['binds_candidate_sha256'] != ch or decision['binds_candidate_sha256'] != ch
        or decision['binds_review_sha256'] != lineage['review']['sha256']
        or final['binds_candidate_sha256'] != ch
        or final['binds_decision_sha256'] != lineage['decision']['sha256']
        or decision['status'] != 'ACCEPT_FOR_PROSPECTIVE_FREEZE'
        or decision['unresolved_blockers'] != []):
        raise ValueError('MTA independent lineage mismatch')
    sources = config['source_sha256']
    verify_sources(sources)
    if (candidate['runtime_source_sha256'] != sources or candidate['runtime'] != config['runtime']
        or candidate['seed_ids'] != config['seeds'] or final['runtime_source_sha256'] != sources
        or final['runtime'] != config['runtime']):
        raise ValueError('Reviewed MTA runtime differs from launch')
    receipt = read_ref(config['central_prelaunch_receipt'])
    if (receipt.get('status') != 'CENTRAL_PRELAUNCH_PASS'
        or receipt['freeze_contract_sha256'] != config['freeze_contract']['sha256']
        or receipt['candidate_sha256'] != ch or receipt['exit_code'] != 0
        or not receipt['stdout'].splitlines()[0].startswith('PASS experiment freeze PRELAUNCH: ')):
        raise ValueError('Missing exact local central prelaunch receipt')
    approval = read_ref(config['public_approval'])
    if (approval.get('approved_by') != 'author'
        or approval.get('action') != 'publish_mta_runtime_amendment'
        or approval['freeze_contract_sha256'] != config['freeze_contract']['sha256']
        or not approval.get('verbatim_user_instruction')):
        raise ValueError('MTA user authorization is absent')
    public = config['public_release']
    if public['repository'] != REPO or public['package_prefix'] != PREFIX:
        raise ValueError('Unexpected MTA public repository/prefix')
    tag = public['tag']
    if not tag or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in tag):
        raise ValueError('Invalid public tag')
    release = remote_json('https://api.github.com/repos/' + REPO + '/releases/tags/' + tag)
    if release.get('draft') or release.get('prerelease') or config['freeze_contract']['sha256'] not in release.get('body',''):
        raise ValueError('Public MTA release does not bind this contract')
    published = original.timestamp(release['published_at'])
    times = [candidate['at'], review['at'], decision['at'], final['at'], receipt['at'], approval['approved_at']]
    parsed = [original.timestamp(t) for t in times]
    if parsed != sorted(parsed) or not parsed[-1] <= published <= original.timestamp(original.now()):
        raise ValueError('Invalid prospective MTA chronology')
    commit = remote_json('https://api.github.com/repos/' + REPO + '/commits/' + tag)['sha']
    refs = subprocess.check_output(['git','ls-remote','https://github.com/' + REPO + '.git',
        'refs/tags/' + tag, 'refs/tags/' + tag + '^{}'], text=True, timeout=30).splitlines()
    refs = {row.split()[1]: row.split()[0] for row in refs}
    observed = refs.get('refs/tags/' + tag + '^{}', refs.get('refs/tags/' + tag))
    if commit != observed or commit != public['commit_sha']:
        raise ValueError('Git and REST MTA commit disagreement')
    bound = dict(sources)
    for r in [config['freeze_contract'], *lineage.values(), candidate['protocol_ref'],
              candidate['runtime_observation_ref'], candidate['planned_artifacts']['unit_inventory_ref']]:
        ref_path(r)
        bound[r['path']] = r['sha256']
    for path, digest in bound.items():
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/' for c in path):
            raise ValueError('Invalid public artifact path')
        with urllib.request.urlopen('https://raw.githubusercontent.com/' + REPO + '/' + commit + '/' + PREFIX + path, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('MTA public byte mismatch: ' + path)
    measured = subprocess.run([sys.executable, str(BASE / 'fresh_worker.py'), 'runtime'],
        capture_output=True, text=True, check=True, env=original.child_env(), timeout=60)
    runtime = json.loads(measured.stdout)
    if runtime != config['runtime'] or runtime['os_family'] != 'Linux':
        raise ValueError('MTA numerical runtime drift')
    cb = frozen['confirmatory_binding']
    return {'mode':'FRESH_SCIENTIFIC', 'run_id':RUN,
        'freeze': {'freeze_id':frozen['freeze_id'], 'final_sha256':lineage['final']['sha256'],
                   'decision_sha256':lineage['decision']['sha256'], 'threshold_id':cb['threshold_id'],
                   'threshold_value':cb['threshold_value'], 'timebase':frozen['timebase_binding']['design_timebase']},
        'launch_config_sha256':original.sha(config_path), 'source_sha256':sources, 'runtime':runtime,
        'freeze_contract_sha256':config['freeze_contract']['sha256'], 'published_at':release['published_at'],
        'final_at':final['at'], 'approved_at':approval['approved_at'], 'public_commit_sha':commit,
        'public_approval_sha256':config['public_approval']['sha256'],
        'central_prelaunch_receipt_sha256':config['central_prelaunch_receipt']['sha256'],
        'execution_host':'mta-cuda', 'completed_experiments_rerun':False}

def new_manifest(root, binding, binding_sha, planned_units, fixture):
    # Same measured envelope keys as the central consumer; validate locally
    # after custody. No workflow library is deployed to the experiment node.
    envelope = {'os_family': platform.system().lower(), 'arch': platform.machine().lower(),
                'python': platform.python_version(), 'host': platform.node()}
    if not all(envelope.values()):
        raise ValueError('Incomplete measured MTA environment')
    if fixture:
        source_paths = [BASE/'fresh_supervisor.py', BASE/'fresh_owned_worker.py',
                        BASE/'supervisor_fixture_worker.py', *[PROJECT/p for p in sorted(EXTRA)]]
        sources = {p.relative_to(PROJECT).as_posix(): original.sha(p) for p in source_paths}
    else:
        sources = dict(binding['source_sha256'])
        verify_sources(sources)
    created = datetime.now(timezone.utc)
    if not fixture and original.timestamp(binding['published_at']) > created:
        raise ValueError('Manifest would precede public freeze')
    record = {'run_id':root.name, 'environment':envelope, 'hostname':envelope['host'],
        'created_at_utc':created.strftime('%Y-%m-%dT%H:%M:%SZ'), 'created_at':created.isoformat(),
        'status':'initializing', 'snapshot_ready':False, 'binding':binding, 'binding_sha256':binding_sha,
        'planned_units':planned_units, 'operation_id':'f07-mta-fresh-to-round-f-20260920',
        'deadline_at':(created+timedelta(hours=12)).isoformat(),
        'code_snapshot':{'path':'code_snapshot','source_sha256':sources},
        'code_snapshot_sha256':hashlib.sha256(original.canonical(sources)).hexdigest()}
    if not fixture:
        record['freeze']=dict(binding['freeze'])
    return record

class SubprocessAdapter:
    def __getattr__(self, name):
        return getattr(subprocess, name)

    def Popen(self, command, *args, **kwargs):
        command = list(command)
        if len(command)>1 and Path(command[1]).resolve()==BASE/'fresh_owned_worker.py':
            command[1]=str(HERE/'mta_owned_worker.py')
        return subprocess.Popen(command, *args, **kwargs)

def configure():
    from mta_process_tree import install
    install()
    original.subprocess = SubprocessAdapter()
    original.launch_binding = launch_binding
    original.verify_sources = verify_sources
    original.new_manifest = new_manifest

def main():
    configure()
    return original.main()

if __name__ == '__main__':
    raise SystemExit(main())

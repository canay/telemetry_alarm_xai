"""Race/crash tests using only synthetic workers and a harmless parent process.

Date/time: 2026-09-20 01:02 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919; findings RT02/RT03
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import json
import subprocess
import sys
import time
import psutil
import fresh_supervisor as supervisor

HERE = Path(__file__).resolve().parent
SELF = Path(__file__).resolve()


def probe(root):
    return subprocess.run([sys.executable, str(SELF), '--probe-mutex', str(root)],
                          capture_output=True, text=True, timeout=10)


def kill(process):
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    parser.add_argument('--hold-parent', action='store_true')
    parser.add_argument('--probe-mutex', type=Path)
    args = parser.parse_args()
    if args.hold_parent:
        time.sleep(30)
        return 0
    if args.probe_mutex:
        try:
            with supervisor.runtime_mutex(args.probe_mutex):
                return 0
        except OSError:
            return 42
    if not args.output or not args.output.replace('_', '').isalnum():
        raise ValueError('Simple new output required')
    root = HERE / args.output
    root.mkdir(exist_ok=False)
    checks = []
    with supervisor.runtime_mutex(root):
        assert probe(root).returncode == 42
    assert probe(root).returncode == 0
    checks.append('kernel_mutex_excludes_second_process_then_releases')
    observed = []
    original_inventory = supervisor.checkpoint_inventory

    def verified_inventory(run_root, *rest):
        assert probe(run_root).returncode == 42, 'Checkpoint inventory is outside ownership'
        observed.append(str(run_root))
        return original_inventory(run_root, *rest)

    locked_name = args.output + '_inventory'
    with patch.object(supervisor, 'checkpoint_inventory', verified_inventory), patch.object(
            sys, 'argv', ['fresh_supervisor', '--fixture', '--output', locked_name, '--stop-after', '1']):
        assert supervisor.main() == 75
    assert len(observed) == 1
    checks.append('authoritative_checkpoint_inventory_runs_under_mutex')
    before_manifest = json.loads((HERE / locked_name / 'RUN_MANIFEST.json').read_bytes())
    result = subprocess.run([sys.executable, str(HERE / 'fresh_supervisor.py'), '--fixture',
                             '--output', locked_name], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    after_manifest = json.loads((HERE / locked_name / 'RUN_MANIFEST.json').read_bytes())
    assert before_manifest['deadline_at'] == after_manifest['deadline_at']
    checks.append('resume_does_not_reset_fixed_run_deadline')
    # Do not kill user processes: these two parent/worker pairs are created here.
    for armed in (False, True):
        parent = subprocess.Popen([sys.executable, str(SELF), '--hold-parent'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child = None
        try:
            born = psutil.Process(parent.pid).create_time()
            output = root / ('armed.json' if armed else 'unarmed.json')
            ticket = root / ('armed.ticket.lock' if armed else 'unarmed.ticket.lock')
            command = [str(HERE / 'supervisor_fixture_worker.py'), '--unit', 'fixture_0', '--output', str(output)]
            child = subprocess.Popen([sys.executable, str(HERE / 'fresh_owned_worker.py'),
                 '--parent-pid', str(parent.pid), '--parent-born', str(born),
                 '--ticket', str(ticket), '--launch-id', 'synthetic_guard', '--', *command],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if armed:
                supervisor.atomic(ticket, {'launch_id': 'synthetic_guard', 'pid': child.pid,
                    'process_created_at': psutil.Process(child.pid).create_time(), 'command': command})
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    timing = psutil.Process(child.pid).cpu_times()
                    if timing.user + timing.system > .3:
                        break
                    time.sleep(.025)
                else:
                    raise AssertionError('Synthetic worker did not advance')
            else:
                time.sleep(.3)
            assert not output.exists()
            kill(parent)
            assert child.wait(timeout=5) == 74
            assert not output.exists()
            checks.append('armed_worker_stops_on_parent_loss' if armed else 'unrecorded_unarmed_worker_never_executes')
        finally:
            if child is not None:
                kill(child)
            kill(parent)
    report = {'status': 'PASS_SYNTHETIC_RACE_AND_PARENT_OWNERSHIP_ONLY', 'count': len(checks),
              'checks': checks, 'at': datetime.now(timezone.utc).isoformat(), 'tool': 'Codex',
              'model': 'gpt-6-astra / xhigh', 'operation_id': 'f07-auto-preflight-20260919',
              'model_fit_executed': False, 'scientific_worker_executed': False,
              'source_sha256': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                   for name in ('fresh_supervisor.py', 'fresh_owned_worker.py', SELF.name)}}
    supervisor.atomic(root / 'REPORT.json', report)
    print(json.dumps({'status': report['status'], 'checks': len(checks)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

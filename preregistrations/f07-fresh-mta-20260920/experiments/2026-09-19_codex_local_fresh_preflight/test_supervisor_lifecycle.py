"""Synthetic stop/resume/crash/hash checks; never calls a scientific worker.

Date/time: 2026-09-20 00:44 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import time
import psutil

HERE = Path(__file__).resolve().parent
SUPERVISOR = HERE / 'fresh_supervisor.py'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call(name, *extra):
    return subprocess.run([sys.executable, str(SUPERVISOR), '--fixture', '--output', name, *extra],
                          capture_output=True, text=True, timeout=45)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args()
    if not args.prefix.replace('_', '').isalnum():
        raise ValueError('Simple new prefix required')
    name, crash_name = args.prefix + '_clean', args.prefix + '_crash'
    if any((HERE / n).exists() for n in (name, crash_name, args.prefix + '_REPORT.json')):
        raise ValueError('Existing fixture output is immutable')
    checks = []
    first = call(name, '--stop-after', '1')
    assert first.returncode == 75, first.stdout + first.stderr
    root = HERE / name
    cp = root / 'checkpoints/fixture_0.json'
    completed = root / 'fixture_0.json'
    before = {str(p): sha(p) for p in (cp, completed)}
    checks.append('controlled_stop_exit_75')
    resumed = call(name)
    assert resumed.returncode == 0 and 'SKIPPED_HASH_VERIFIED' in resumed.stdout
    assert all(sha(Path(p)) == digest for p, digest in before.items())
    checks.append('resume_preserves_completed_unit_exactly')
    beats = [json.loads(line) for path in (root / 'heartbeats').glob('*.jsonl')
             for line in path.read_text(encoding='utf-8').splitlines()]
    cpu = [b['process_tree_cpu_seconds'] for b in beats if b['unit_id'] == 'fixture_0']
    assert len(cpu) >= 2 and max(cpu) > min(cpu)
    checks.append('heartbeat_reports_cpu_advancement_inside_unit')
    raw = completed.read_bytes()
    try:
        completed.write_bytes(raw + b' ')
        bad = call(name, '--plan')
        assert bad.returncode != 0 and 'Checkpoint output drift' in bad.stderr
        checks.append('corrupt_completed_artifact_rejected_before_resume')
    finally:
        completed.write_bytes(raw)
        assert sha(completed) == before[str(completed)]
    # Simulate an abrupt stop of this test's own supervisor/worker, not user processes.
    crash = HERE / crash_name
    process = subprocess.Popen([sys.executable, str(SUPERVISOR), '--fixture', '--output', crash_name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    owned = []
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            lock_path = crash / 'supervisor.lock'
            if lock_path.exists():
                locked = json.loads(lock_path.read_bytes())
                if locked.get('child_pid'):
                    break
            time.sleep(.05)
        else:
            raise AssertionError('Fixture child identity was not recorded')
        parent = psutil.Process(process.pid)
        assert parent.create_time() == locked['process_created_at']
        child = psutil.Process(locked['child_pid'])
        assert child.create_time() == locked['child_created_at']
        owned = [child, parent]
        for proc in owned:
            proc.kill()
        psutil.wait_procs(owned, timeout=5)
        process.wait(timeout=5)
        assert lock_path.exists() and not (crash / 'checkpoints/fixture_0.json').exists()
        rejected = call(crash_name)
        assert rejected.returncode != 0
        checks.append('abrupt_stop_leaves_lock_and_blocks_blind_restart')
        recovered = call(crash_name, '--recover-stale-lock')
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr
        assert list((crash / 'attempts').glob('stale_lock_*.json'))
        checks.append('dead_process_identity_checked_recovery_preserves_old_lock')
    finally:
        for proc in owned:
            if proc.is_running():
                proc.kill()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    report = {'status': 'PASS_SYNTHETIC_SUPERVISOR_LIFECYCLE_ONLY', 'checks': checks,
              'count': len(checks), 'at': datetime.now(timezone.utc).isoformat(), 'tool': 'Codex',
              'model': 'gpt-6-astra / xhigh', 'operation_id': 'f07-auto-preflight-20260919',
              'supervisor_sha256': sha(SUPERVISOR), 'test_sha256': sha(Path(__file__)),
              'scientific_worker_executed': False, 'model_fit_executed': False,
              'completed_unit_hashes_preserved': before}
    with (HERE / (args.prefix + '_REPORT.json')).open('xb') as stream:
        stream.write((json.dumps(report, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'status': report['status'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()

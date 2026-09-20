"""MTA synthetic diagnostic only; no scientific fit or endpoint access.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
"""
import json, subprocess, sys, time
from pathlib import Path
import psutil
import mta_supervisor as adapter
adapter.configure()
base = adapter.BASE
root = base / 'mta_parent_diagnostic_20260920'
root.mkdir(exist_ok=False)
rows = []
for armed in (False, True):
    parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    born = psutil.Process(parent.pid).create_time()
    output = root / f'{armed}.json'
    ticket = root / f'{armed}.ticket'
    command = [str(base / 'supervisor_fixture_worker.py'), '--unit', 'fixture_0', '--output', str(output)]
    child = subprocess.Popen([sys.executable, str(base / 'fresh_owned_worker.py'), '--parent-pid', str(parent.pid),
        '--parent-born', str(born), '--ticket', str(ticket), '--launch-id', 'diagnostic', '--', *command],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if armed:
            adapter.original.atomic(ticket, {'launch_id':'diagnostic', 'pid':child.pid,
                'process_created_at':psutil.Process(child.pid).create_time(), 'command':command})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    break
                timing = psutil.Process(child.pid).cpu_times()
                if timing.user + timing.system > .3:
                    break
                time.sleep(.025)
        else:
            time.sleep(.3)
        parent.kill(); parent.wait(timeout=5)
        out, err = child.communicate(timeout=5)
        rows.append({'armed':armed, 'exit_code':child.returncode, 'stdout':out, 'stderr':err,
                     'output_exists':output.exists()})
    finally:
        for proc in (child,parent):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
adapter.original.atomic(root / 'DIAGNOSTIC.json', {'rows':rows, 'scientific_compute':False})
print(json.dumps(rows), flush=True)
import test_fresh_integration as integration
sys.argv = ['test_fresh_integration.py', '--output', 'mta_integration_20260920']
integration.main()

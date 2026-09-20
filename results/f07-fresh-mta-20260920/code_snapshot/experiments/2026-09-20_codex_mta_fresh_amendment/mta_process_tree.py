"""Enumerate only an owned Linux subtree through kernel child lists.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
Avoid a system-wide /proc scan competing with a Python CPU-bound worker.
No process is signalled here. Callers retain their PID/birth ownership checks.
"""
from pathlib import Path
import os
import psutil

def children(self, recursive=False):
    if os.name != 'posix' or not Path('/proc/self/task').is_dir():
        raise RuntimeError('MTA Linux procfs required')
    if not self.is_running():
        raise psutil.NoSuchProcess(self.pid)
    pending = [self]
    found, seen = [], {self.pid}
    while pending:
        parent = pending.pop()
        if not parent.is_running():
            continue
        tasks = Path('/proc') / str(parent.pid) / 'task'
        try:
            tids = list(tasks.iterdir())
        except FileNotFoundError:
            continue
        pids = set()
        for tid in tids:
            try:
                pids.update(int(value) for value in (tid/'children').read_text().split())
            except FileNotFoundError:
                continue
        for pid in sorted(pids):
            if pid in seen:
                continue
            try:
                child = psutil.Process(pid)
                if (not parent.is_running() or child.ppid() != parent.pid
                        or child.create_time() < parent.create_time()):
                    continue
                seen.add(pid)
                found.append(child)
                if recursive:
                    pending.append(child)
            except psutil.NoSuchProcess:
                continue
    return found

def install():
    psutil.Process.children = children

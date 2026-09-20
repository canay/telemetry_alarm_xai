"""Crash-safe launch handshake; no scientific code before durable authorization.

Date/time: 2026-09-20 00:55 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919; finding RT03
The parent records this PID/birth before issuing the one-launch ticket.
Parent loss stops this process and its own descendants, never user processes.
"""
from pathlib import Path
import argparse
import json
import os
import runpy
import sys
import threading
import time
import psutil


def parent_alive(pid, born):
    try:
        return psutil.Process(pid).create_time() == born
    except psutil.NoSuchProcess:
        return False


def watch_parent(pid, born, stop):
    while not stop.wait(.1):
        if not parent_alive(pid, born):
            for child in psutil.Process().children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            os._exit(74)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--parent-born', type=float, required=True)
    parser.add_argument('--ticket', type=Path, required=True)
    parser.add_argument('--launch-id', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command or args.command[0] != '--' or len(args.command) < 3:
        raise ValueError('Exact Python script command required')
    command = args.command[1:]
    script = Path(command[0]).resolve()
    here = Path(__file__).resolve().parent
    if script.parent != here or script.name not in ('fresh_worker.py', 'supervisor_fixture_worker.py'):
        raise ValueError('Only declared local workers are allowed')
    pid, born = os.getpid(), psutil.Process().create_time()
    stop = threading.Event()
    threading.Thread(target=watch_parent, args=(args.parent_pid, args.parent_born, stop), daemon=True).start()
    deadline = time.monotonic() + 30
    try:
        while True:
            if not parent_alive(args.parent_pid, args.parent_born):
                return 74
            if args.ticket.exists():
                ticket = json.loads(args.ticket.read_bytes())
                if (ticket.get('launch_id') != args.launch_id or ticket.get('pid') != pid
                        or ticket.get('process_created_at') != born
                        or ticket.get('command') != command):
                    raise ValueError('Launch ticket mismatch')
                break
            if time.monotonic() > deadline:
                raise TimeoutError('No durable launch ticket')
            time.sleep(.025)
        # Check again after ticket parsing; the watchdog remains active inside the worker.
        if not parent_alive(args.parent_pid, args.parent_born):
            return 74
        sys.argv = command
        runpy.run_path(str(script), run_name='__main__')
        return 0
    finally:
        stop.set()


if __name__ == '__main__':
    raise SystemExit(main())

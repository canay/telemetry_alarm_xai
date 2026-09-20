"""MTA parent watchdog adapter; immutable worker handshake and science.
Date/time: 2026-09-20; Tool: Codex; Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
"""
from pathlib import Path
import sys
from mta_process_tree import install
BASE=Path(__file__).resolve().parent.parent/'2026-09-19_codex_local_fresh_preflight'
sys.path.insert(0,str(BASE))
import fresh_owned_worker
if __name__ == '__main__':
    install()
    raise SystemExit(fresh_owned_worker.main())

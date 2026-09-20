"""Synthetic lifecycle worker: no scientific imports, data, or seed parameters.

Date/time: 2026-09-20 00:39 +03:00; Tool: Codex; Model: gpt-6-astra/xhigh
Operation ID: f07-auto-preflight-20260919
"""
import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--unit', choices=('fixture_0', 'fixture_1'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    start = time.monotonic()
    iterations = 0
    checksum = 0
    while time.monotonic() - start < 2:
        checksum = (checksum * 1103515245 + 12345) % (2**31)
        iterations += 1
    with args.output.open('xb') as stream:
        stream.write((json.dumps({'unit_id': args.unit, 'synthetic_fixture': True,
                                 'iterations': iterations, 'checksum': checksum}) + '\n').encode('utf-8'))


if __name__ == '__main__':
    main()

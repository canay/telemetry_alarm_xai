"""Durable launcher for endpoint-blind V5 pilot and discovery re-estimation.

Operation: f07-prospective-confirmation-v5-20260828
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import criticality_analysis_v4 as v4
from confirmatory_analysis_v5 import (
    EXPECTED_KILL_SWITCHES,
    PLAN_NAME as CONFIRMATORY_PLAN_NAME,
    RELEASE_TAG as CONFIRMATORY_TAG,
    REPO as CONFIRMATORY_REPO,
    REQUIRED_FROZEN_FILES,
    SEEDS as CONFIRMATORY_SEEDS,
)
from criticality_generator_v5 import N_TEST_REPLICATES
import models as M


CODE_FILES = (
    "common.py",
    "models.py",
    "telemetry_generator.py",
    "criticality_generator.py",
    "criticality_generator_v5.py",
    "run_criticality_unit.py",
    "run_criticality_unit_v5.py",
    "criticality_analysis_v4.py",
    "criticality_property_v5.py",
    "criticality_analysis_v5.py",
    "confirmatory_analysis_v5.py",
    "power_freeze_v5.py",
    "property_pilot_v5.py",
    "run_v5_development.py",
    "test_v5_contract.py",
)

CONTROLLED_DIRS = ("data", "ckpt", "raw", "replicates", "analysis_ckpt", "metrics")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, encoding="utf-8").strip()


def verify_public_release(release_root: Path) -> tuple[dict, str, dict]:
    plan_path = release_root / CONFIRMATORY_PLAN_NAME
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("release_tag") != CONFIRMATORY_TAG:
        raise RuntimeError("V5 confirmatory plan release tag mismatch")
    if plan.get("seeds") != list(CONFIRMATORY_SEEDS):
        raise RuntimeError("V5 confirmatory plan seed set mismatch")
    if plan.get("confirmation_n") != len(CONFIRMATORY_SEEDS):
        raise RuntimeError("V5 confirmatory plan sample size mismatch")
    if set(plan.get("code_sha256", {})) != REQUIRED_FROZEN_FILES:
        raise RuntimeError("V5 frozen-file set mismatch")
    for relative, expected in plan["code_sha256"].items():
        if sha256(release_root / relative) != expected:
            raise RuntimeError(f"V5 frozen hash mismatch: {relative}")
    head = output(["git", "-C", str(release_root), "rev-parse", "HEAD"])
    local_tag = output(
        ["git", "-C", str(release_root), "rev-list", "-n", "1", CONFIRMATORY_TAG]
    )
    if head != local_tag:
        raise RuntimeError("V5 release checkout HEAD does not equal local tag commit")
    if output(["git", "-C", str(release_root), "status", "--porcelain"]):
        raise RuntimeError("V5 release checkout is not clean")
    origin = output(["git", "-C", str(release_root), "remote", "get-url", "origin"])
    if origin not in {
        "https://github.com/canay/telemetry_alarm_xai.git",
        "git@github.com:canay/telemetry_alarm_xai.git",
    }:
        raise RuntimeError(f"unexpected V5 release origin: {origin}")
    remote_tag_line = output(
        [
            "git", "-C", str(release_root), "ls-remote", "--tags", "origin",
            f"refs/tags/{CONFIRMATORY_TAG}",
        ]
    )
    remote_tag = remote_tag_line.split()[0] if remote_tag_line else ""
    api_tag = output(
        [
            "gh", "api", f"repos/{CONFIRMATORY_REPO}/git/ref/tags/{CONFIRMATORY_TAG}",
            "--jq", ".object.sha",
        ]
    )
    if remote_tag != head or api_tag != head:
        raise RuntimeError("remote V5 tag does not bind local release commit")
    release = json.loads(
        output(
            [
                "gh", "release", "view", CONFIRMATORY_TAG,
                "--repo", CONFIRMATORY_REPO,
                "--json", "tagName,publishedAt,url,body",
            ]
        )
    )
    if release.get("tagName") != CONFIRMATORY_TAG or not release.get("publishedAt"):
        raise RuntimeError("remote V5 release is missing or unpublished")
    plan_match = re.search(r"plan_sha256=([0-9a-f]{64})", release.get("body", ""))
    if not plan_match or plan_match.group(1) != sha256(plan_path):
        raise RuntimeError("remote V5 release body does not bind the plan hash")
    return plan, head, release


def verify_registered_confirmation_tree(
    run_root: Path, manifest: dict, published: datetime
) -> None:
    registered = manifest.get("artifact_sha256", {})
    for directory in CONTROLLED_DIRS:
        root = run_root / directory
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(run_root).as_posix()
            if relative not in registered:
                raise RuntimeError(f"unregistered V5 confirmation artifact: {relative}")
            if sha256(path) != registered[relative]:
                raise RuntimeError(f"registered V5 confirmation artifact drift: {relative}")
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) <= published:
                raise RuntimeError(f"V5 confirmation artifact predates release: {relative}")


def status(run_root: Path, mode: str, state: str, detail: str) -> None:
    now = datetime.now().astimezone()
    content = (
        f"# V5 {mode} status\n\n"
        f"Date/time: {now:%Y-%m-%d %H:%M %z}\n"
        "Tool: Codex\n"
        "Model, if known: GPT-5\n"
        f"Operation ID: `f07-v5-{mode}-20260828`\n\n"
        f"- State: `{state}`\n"
        f"- Detail: {detail}\n"
        "- This file is a live execution view; RUN_MANIFEST.json is canonical.\n"
    )
    temporary = run_root / "STATUS.md.tmp"
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, run_root / "STATUS.md")


def run(command: list[str], label: str) -> tuple[str, float]:
    started = time.monotonic()
    completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(
            f"unit failed {label} rc={completed.returncode}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return label, time.monotonic() - started


def artifacts_for(run_root: Path, label: str) -> list[Path]:
    parts = label.split(":")
    seed = int(parts[1])
    if parts[0] == "gen":
        return [run_root / "data" / f"telemetry_seed{seed}.npz"]
    if parts[0] == "feat":
        return [
            path
            for replicate in range(N_TEST_REPLICATES)
            for path in (
                run_root
                / "replicates"
                / f"r{replicate}"
                / "data"
                / f"telemetry_seed{seed}.npz",
                run_root
                / "replicates"
                / f"r{replicate}"
                / "ckpt"
                / f"feat_seed{seed}.npz",
            )
        ]
    if parts[0] == "model":
        model = parts[2]
        result = [
            run_root / "raw" / f"model_seed{seed}_{model}.json",
            run_root / "ckpt" / f"model_seed{seed}_{model}.npz",
        ]
        for replicate in range(N_TEST_REPLICATES):
            root = run_root / "replicates" / f"r{replicate}"
            result.extend(
                [
                    root / "raw" / f"model_seed{seed}_{model}.json",
                    root / "ckpt" / f"model_seed{seed}_{model}.npz",
                ]
            )
        return result
    if parts[0] == "cross":
        return [run_root / "raw" / f"cross_seed{seed}.json"]
    raise ValueError(label)


def phase(
    name: str,
    labels: list[str],
    base: list[str],
    workers: int,
    run_root: Path,
    manifest: dict,
    manifest_path: Path,
    mode: str,
    published: datetime | None = None,
) -> None:
    pending = []
    for label in labels:
        artifacts = artifacts_for(run_root, label)
        if all(path.exists() for path in artifacts):
            expected = manifest["artifact_sha256"]
            for path in artifacts:
                relative = path.relative_to(run_root).as_posix()
                if published is not None and relative not in expected:
                    raise RuntimeError(
                        f"unregistered resumed confirmation artifact: {relative}"
                    )
                if relative in expected and expected[relative] != sha256(path):
                    raise RuntimeError(f"registered artifact drift: {relative}")
                if (
                    published is not None
                    and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                    <= published
                ):
                    raise RuntimeError(
                        f"resumed confirmation artifact predates release: {relative}"
                    )
            print(f"V5_HEARTBEAT phase={name} resumed={label}", flush=True)
        else:
            pending.append(label)
    completed_count = len(labels) - len(pending)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run, [*base, label], label): label for label in pending}
        for future in as_completed(futures):
            label, elapsed = future.result()
            for path in artifacts_for(run_root, label):
                if not path.is_file():
                    raise RuntimeError(f"expected artifact missing: {path}")
                if (
                    published is not None
                    and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                    <= published
                ):
                    raise RuntimeError(
                        f"new confirmation artifact predates release: {path}"
                    )
                manifest["artifact_sha256"][
                    path.relative_to(run_root).as_posix()
                ] = sha256(path)
            completed_count += 1
            manifest["last_completed_unit"] = label
            manifest["last_heartbeat_at"] = datetime.now().astimezone().isoformat()
            atomic_json(manifest_path, manifest)
            status(
                run_root,
                mode,
                f"RUNNING_{name.upper()}",
                f"{completed_count}/{len(labels)}; last={label}",
            )
            print(
                f"V5_HEARTBEAT phase={name} completed={completed_count}/{len(labels)} "
                f"unit={label} unit_elapsed={elapsed:.1f}s "
                f"phase_elapsed={time.monotonic() - started:.1f}s",
                flush=True,
            )


def register_tree(
    root: Path,
    run_root: Path,
    manifest: dict,
    published: datetime | None,
) -> None:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if (
            published is not None
            and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) <= published
        ):
            raise RuntimeError(f"confirmation output predates release: {path}")
        manifest["artifact_sha256"][path.relative_to(run_root).as_posix()] = sha256(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("pilot", "discovery", "confirmation"), required=True
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--null-draws", type=int, default=200)
    parser.add_argument("--nested-reference-run", type=Path)
    parser.add_argument("--release-root", type=Path)
    args = parser.parse_args()
    if not 1 <= args.max_workers <= 4:
        raise ValueError("max-workers must be between 1 and 4")
    seeds = v4.parse_seed_spec(args.seeds)
    if args.mode == "pilot" and seeds != list(range(200, 210)):
        raise ValueError("V5 pilot seeds must be exactly 200-209")
    if args.mode == "discovery" and seeds != list(range(0, 10)):
        raise ValueError("V5 discovery seeds must be exactly 0-9")
    if args.mode == "confirmation" and seeds != list(CONFIRMATORY_SEEDS):
        raise ValueError("V5 confirmation seeds must be exactly 300-319")
    if args.mode == "confirmation" and args.release_root is None:
        raise ValueError("V5 confirmation requires --release-root")
    if args.mode == "pilot" and N_TEST_REPLICATES == 7 and args.nested_reference_run is None:
        raise ValueError("R=7 pilot requires --nested-reference-run for R=3 reproduction")
    code = Path(__file__).resolve().parent
    code_hashes = {name: sha256(code / name) for name in CODE_FILES}
    plan = None
    release_commit = None
    release = None
    published = None
    if args.mode == "confirmation":
        plan, release_commit, release = verify_public_release(args.release_root.resolve())
        published = datetime.fromisoformat(
            release["publishedAt"].replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        if datetime.now(timezone.utc) <= published:
            raise RuntimeError("system clock is not later than public release time")
    identity = {
        "schema_version": 5,
        "operation_id": f"f07-v5-{args.mode}-20260828",
        "mode": args.mode,
        "seeds": seeds,
        "models": list(M.MODELS),
        "primary_models": list(v4.PRIMARY_CONFIRMATORY_MODELS),
        "n_test_replicates": N_TEST_REPLICATES,
        "test_orbits_per_replicate": 130,
        "minimum_pooled_episodes": 20,
        "null_draws": 0 if args.mode == "pilot" else args.null_draws,
        "code_sha256": code_hashes,
    }
    if args.mode == "confirmation":
        identity.update(
            {
                "release_tag": CONFIRMATORY_TAG,
                "release_commit": release_commit,
                "release_url": release["url"],
                "release_published_at_utc": release["publishedAt"],
                "plan_sha256": sha256(
                    args.release_root.resolve() / CONFIRMATORY_PLAN_NAME
                ),
                "decision_method": plan["decision_method"],
            }
        )
    run_contract = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    args.run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.run_root / "RUN_MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("run_contract_sha256") != run_contract:
            raise RuntimeError("existing development run contract mismatch")
        if published is not None:
            verify_registered_confirmation_tree(args.run_root, manifest, published)
    else:
        if any(args.run_root.iterdir()):
            raise RuntimeError("first development start requires an empty run root")
        manifest = {
            **identity,
            "run_contract_sha256": run_contract,
            "status": "STARTED",
            "run_started_at": datetime.now().astimezone().isoformat(),
            "artifact_sha256": {},
        }
        atomic_json(manifest_path, manifest)
    status(args.run_root, args.mode, "STARTED", f"seeds={args.seeds}")
    python = sys.executable
    base = [
        python,
        str(code / "run_criticality_unit_v5.py"),
        "--run-root",
        str(args.run_root),
    ]
    phase(
        "generate",
        [f"gen:{seed}" for seed in seeds],
        base,
        args.max_workers,
        args.run_root,
        manifest,
        manifest_path,
        args.mode,
        published,
    )
    phase(
        "features",
        [f"feat:{seed}" for seed in seeds],
        base,
        args.max_workers,
        args.run_root,
        manifest,
        manifest_path,
        args.mode,
        published,
    )
    phase(
        "models",
        [f"model:{seed}:{model}" for seed in seeds for model in M.MODELS],
        base,
        args.max_workers,
        args.run_root,
        manifest,
        manifest_path,
        args.mode,
        published,
    )
    if args.mode == "pilot":
        command = [
            python,
            str(code / "property_pilot_v5.py"),
            "--run-root",
            str(args.run_root),
            "--seeds",
            args.seeds,
        ]
        if args.nested_reference_run is not None:
            command.extend(["--nested-reference-run", str(args.nested_reference_run)])
        subprocess.run(command, check=True)
        output = args.run_root / "metrics" / "property_pilot_v5.json"
        manifest["artifact_sha256"][output.relative_to(args.run_root).as_posix()] = sha256(output)
        manifest["status"] = "PROPERTY_PILOT_PASS"
    else:
        phase(
            "cross",
            [f"cross:{seed}" for seed in seeds],
            base,
            args.max_workers,
            args.run_root,
            manifest,
            manifest_path,
            args.mode,
            published,
        )
        property_completed = subprocess.run(
            [
                python,
                str(code / "criticality_property_v5.py"),
                "--run-root",
                str(args.run_root),
                "--seeds",
                args.seeds,
            ],
            text=True,
            capture_output=True,
            encoding="utf-8",
        )
        if property_completed.stdout:
            print(property_completed.stdout, end="")
        if property_completed.stderr:
            print(property_completed.stderr, end="", file=sys.stderr)
        property_path = args.run_root / "metrics" / "property_tests.json"
        if property_completed.returncode not in (0, 1) or not property_path.is_file():
            raise RuntimeError(
                f"V5 property process failed rc={property_completed.returncode}"
            )
        register_tree(property_path.parent, args.run_root, manifest, published)
        property_result = json.loads(property_path.read_text(encoding="utf-8"))
        expected_property_status = (
            "PASS" if property_completed.returncode == 0 else "FAIL"
        )
        if property_result.get("status") != expected_property_status:
            raise RuntimeError("V5 property exit code and result status disagree")
        if property_completed.returncode == 1:
            manifest["status"] = "NOT_CONFIRMED_PROPERTY_GATE"
            manifest["completed_at"] = datetime.now().astimezone().isoformat()
            atomic_json(manifest_path, manifest)
            status(
                args.run_root,
                args.mode,
                manifest["status"],
                f"failed_checks={len(property_result.get('failed', []))}",
            )
            print(
                f"V5_{args.mode.upper()}_{manifest['status']} "
                f"run_root={args.run_root}"
            )
            raise SystemExit(2)
        manifest["status"] = "PROPERTY_PASS"
        atomic_json(manifest_path, manifest)
        subprocess.run(
            [
                python,
                str(code / "criticality_analysis_v5.py"),
                "--run-root",
                str(args.run_root),
                "--seeds",
                args.seeds,
                "--null-draws",
                str(args.null_draws),
            ],
            check=True,
        )
        register_tree(args.run_root / "metrics", args.run_root, manifest, published)
        register_tree(args.run_root / "analysis_ckpt", args.run_root, manifest, published)
        construct = json.loads(
            (args.run_root / "metrics" / "construct_validity.json").read_text(
                encoding="utf-8"
            )
        )
        if set(construct.get("kill_switches", {})) != EXPECTED_KILL_SWITCHES:
            raise RuntimeError("V5 construct kill-switch set mismatch")
        fired = {
            key: value
            for key, value in construct["kill_switches"].items()
            if value
        }
        if fired:
            manifest["status"] = "NOT_CONFIRMED_CONSTRUCT_GATE"
            manifest["completed_at"] = datetime.now().astimezone().isoformat()
            atomic_json(manifest_path, manifest)
            status(
                args.run_root,
                args.mode,
                manifest["status"],
                f"fired={','.join(sorted(fired))}",
            )
            print(
                f"V5_{args.mode.upper()}_{manifest['status']} "
                f"run_root={args.run_root}"
            )
            raise SystemExit(2)
        if args.mode == "discovery":
            manifest["status"] = "DISCOVERY_COMPLETE"
        else:
            manifest["status"] = "ANALYSIS_COMPLETE"
            atomic_json(manifest_path, manifest)
            completed = subprocess.run(
                [
                    python,
                    str(code / "confirmatory_analysis_v5.py"),
                    "--run-root",
                    str(args.run_root),
                    "--release-root",
                    str(args.release_root.resolve()),
                    "--release-tag",
                    CONFIRMATORY_TAG,
                    "--release-commit",
                    release_commit,
                ],
                text=True,
                capture_output=True,
                encoding="utf-8",
            )
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
            register_tree(args.run_root / "metrics", args.run_root, manifest, published)
            if completed.returncode not in (0, 2):
                manifest["status"] = "CONFIRMATION_ERROR"
                atomic_json(manifest_path, manifest)
                raise RuntimeError(
                    f"confirmatory decision failed rc={completed.returncode}"
                )
            decision = json.loads(
                (args.run_root / "metrics" / "confirmatory_decision.json").read_text(
                    encoding="utf-8"
                )
            )
            expected_status = "CONFIRMED" if completed.returncode == 0 else "NOT_CONFIRMED"
            if decision.get("status") != expected_status:
                raise RuntimeError("confirmatory exit code and decision status disagree")
            manifest["status"] = expected_status
    manifest["completed_at"] = datetime.now().astimezone().isoformat()
    atomic_json(manifest_path, manifest)
    status(args.run_root, args.mode, manifest["status"], "completed")
    print(f"V5_{args.mode.upper()}_COMPLETE run_root={args.run_root}")


if __name__ == "__main__":
    main()

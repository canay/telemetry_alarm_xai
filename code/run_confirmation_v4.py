"""Execute the remote-bound, public-frozen V4 confirmation.

First start requires an absent or empty run root. Every reusable artifact is
then registered immediately by SHA-256 and must postdate the remote GitHub
release. Unregistered or changed artifacts fail closed.

Operation: f07-criticality-v4-pre-freeze-repair-20260826
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


REPO = "canay/telemetry_alarm_xai"
TAG = "v1.1.0"
SEEDS = tuple(range(10, 30))
MODELS = ("lr", "dtree", "iforest", "hgb", "pca", "ae")
PRIMARY_MODELS = ("lr", "iforest", "hgb", "pca", "ae")
NULL_DRAWS = 200
DECISION_METHOD = "one_sample_student_t_lower_bound"
REQUIRED_FROZEN_FILES = {
    ".gitattributes",
    "code/common.py",
    "code/models.py",
    "code/telemetry_generator.py",
    "code/criticality_generator.py",
    "code/run_criticality_unit.py",
    "code/criticality_analysis_v4.py",
    "code/confirmatory_analysis_v4.py",
    "code/run_confirmation_v4.py",
    "code/power_freeze_v4.py",
    "PROTOCOL_V1_1.md",
    "POWER_PLAN_V4.json",
}
CONTROLLED_DIRS = ("data", "ckpt", "raw", "analysis_ckpt", "metrics")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, encoding="utf-8").strip()


def verify_release(release_root: Path) -> tuple[dict, str, dict]:
    plan_path = release_root / "CONFIRMATORY_PLAN.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("release_tag") != TAG or plan.get("seeds") != list(SEEDS):
        raise RuntimeError("confirmatory plan identity mismatch")
    if set(plan.get("code_sha256", {})) != REQUIRED_FROZEN_FILES:
        raise RuntimeError("confirmatory plan frozen-file set mismatch")
    if plan.get("decision_method") != DECISION_METHOD:
        raise RuntimeError("confirmatory plan decision method mismatch")
    for relative, expected in plan["code_sha256"].items():
        if sha256(release_root / relative) != expected:
            raise RuntimeError(f"frozen code hash mismatch: {relative}")

    head = output(["git", "-C", str(release_root), "rev-parse", "HEAD"])
    local_tag = output(["git", "-C", str(release_root), "rev-list", "-n", "1", TAG])
    if head != local_tag:
        raise RuntimeError("release checkout HEAD does not equal local tag commit")
    if output(["git", "-C", str(release_root), "status", "--porcelain"]):
        raise RuntimeError("release checkout is not clean")
    origin = output(["git", "-C", str(release_root), "remote", "get-url", "origin"])
    if origin not in {
        "https://github.com/canay/telemetry_alarm_xai.git",
        "git@github.com:canay/telemetry_alarm_xai.git",
    }:
        raise RuntimeError(f"unexpected release origin: {origin}")
    remote_tag_line = output(
        ["git", "-C", str(release_root), "ls-remote", "--tags", "origin", f"refs/tags/{TAG}"]
    )
    remote_tag = remote_tag_line.split()[0] if remote_tag_line else ""
    api_tag = output(
        ["gh", "api", f"repos/{REPO}/git/ref/tags/{TAG}", "--jq", ".object.sha"]
    )
    if remote_tag != head or api_tag != head:
        raise RuntimeError(
            f"remote tag mismatch head={head} ls_remote={remote_tag} api={api_tag}"
        )
    release = json.loads(
        output(
            [
                "gh",
                "release",
                "view",
                TAG,
                "--repo",
                REPO,
                "--json",
                "tagName,publishedAt,url,body",
            ]
        )
    )
    if release.get("tagName") != TAG or not release.get("publishedAt"):
        raise RuntimeError("remote release is missing or unpublished")
    plan_hash_match = re.search(r"plan_sha256=([0-9a-f]{64})", release.get("body", ""))
    if not plan_hash_match or plan_hash_match.group(1) != sha256(plan_path):
        raise RuntimeError("release body does not bind the local confirmatory plan")
    return plan, head, release


def run_unit(command: list[str], label: str) -> tuple[str, str]:
    started = time.monotonic()
    completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(
            f"unit failed {label} rc={completed.returncode}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return label, f"{time.monotonic() - started:.1f}s"


def register_file(
    run_root: Path,
    relative: str,
    manifest: dict,
    manifest_path: Path,
    published: datetime,
) -> None:
    path = run_root / relative
    if not path.is_file():
        raise RuntimeError(f"expected artifact missing: {relative}")
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if modified <= published:
        raise RuntimeError(f"artifact predates public release: {relative}")
    manifest["artifact_sha256"][relative] = sha256(path)
    atomic_json(manifest_path, manifest)


def verify_registered_tree(
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
                raise RuntimeError(f"unregistered artifact in resumed run: {relative}")
            if sha256(path) != registered[relative]:
                raise RuntimeError(f"registered artifact hash drift: {relative}")
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) <= published:
                raise RuntimeError(f"registered artifact predates release: {relative}")


def phase(
    name: str,
    commands: list[tuple[str, list[str], list[str]]],
    workers: int,
    run_root: Path,
    manifest: dict,
    manifest_path: Path,
    published: datetime,
) -> None:
    started = time.monotonic()
    pending_commands: list[tuple[str, list[str], list[str]]] = []
    for label, command, artifacts in commands:
        exists = [(run_root / relative).exists() for relative in artifacts]
        if any(exists) and not all(exists):
            raise RuntimeError(f"partial unit artifacts are not resumable: {label}")
        if all(exists):
            for relative in artifacts:
                expected = manifest["artifact_sha256"].get(relative)
                if expected != sha256(run_root / relative):
                    raise RuntimeError(f"unbound or changed resumed unit: {label} {relative}")
            print(f"CONFIRM_V4_HEARTBEAT phase={name} resumed={label}", flush=True)
        else:
            pending_commands.append((label, command, artifacts))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {
            pool.submit(run_unit, command, label): (label, artifacts)
            for label, command, artifacts in pending_commands
        }
        completed_count = len(commands) - len(pending_commands)
        for future in as_completed(pending):
            label, elapsed = future.result()
            artifacts = pending[future][1]
            for relative in artifacts:
                register_file(run_root, relative, manifest, manifest_path, published)
            completed_count += 1
            print(
                f"CONFIRM_V4_HEARTBEAT phase={name} completed={completed_count}/"
                f"{len(commands)} unit={label} unit_elapsed={elapsed} "
                f"phase_elapsed={time.monotonic() - started:.1f}s",
                flush=True,
            )


def register_tree(
    run_root: Path,
    directory: str,
    manifest: dict,
    manifest_path: Path,
    published: datetime,
) -> None:
    root = run_root / directory
    for path in sorted(root.rglob("*")):
        if path.is_file():
            register_file(
                run_root,
                path.relative_to(run_root).as_posix(),
                manifest,
                manifest_path,
                published,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=2)
    args = parser.parse_args()
    if args.max_workers < 1 or args.max_workers > 4:
        raise ValueError("max-workers must be between 1 and 4")

    plan, commit, release = verify_release(args.release_root)
    published = datetime.fromisoformat(release["publishedAt"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) <= published:
        raise RuntimeError("system time does not postdate the public release")
    manifest_path = args.run_root / "RUN_MANIFEST.json"
    first_start = not manifest_path.exists()
    if first_start and args.run_root.exists() and any(args.run_root.iterdir()):
        raise RuntimeError("first confirmatory start requires an empty run root")
    args.run_root.mkdir(parents=True, exist_ok=True)

    identity = {
        "schema_version": 4,
        "operation_id": "f07-criticality-v4-confirmation-20260826",
        "release_tag": TAG,
        "release_commit": commit,
        "release_url": release["url"],
        "release_published_at_utc": release["publishedAt"],
        "plan_sha256": sha256(args.release_root / "CONFIRMATORY_PLAN.json"),
        "seeds": list(SEEDS),
        "models": list(MODELS),
        "primary_models": list(PRIMARY_MODELS),
        "amplitude_scale": 1.0,
        "null_draws": NULL_DRAWS,
        "decision_method": DECISION_METHOD,
    }
    run_contract_sha256 = canonical_sha256(identity)
    if first_start:
        manifest = {
            **identity,
            "run_contract_sha256": run_contract_sha256,
            "status": "STARTED_AFTER_PUBLIC_FREEZE",
            "run_started_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "artifact_sha256": {},
        }
        atomic_json(manifest_path, manifest)
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key, value in identity.items():
            if manifest.get(key) != value:
                raise RuntimeError(f"existing run manifest mismatch: {key}")
        if manifest.get("run_contract_sha256") != run_contract_sha256:
            raise RuntimeError("existing run contract hash mismatch")
        started = datetime.fromisoformat(
            manifest["run_started_at_utc"].replace("Z", "+00:00")
        )
        if started <= published:
            raise RuntimeError("recorded run start does not postdate release")
        verify_registered_tree(args.run_root, manifest, published)

    code = args.release_root / "code"
    runner = code / "run_criticality_unit.py"
    analysis = code / "criticality_analysis_v4.py"
    confirm = code / "confirmatory_analysis_v4.py"
    python = sys.executable
    base = [python, str(runner), "--run-root", str(args.run_root), "--amplitude-scale", "1.0"]
    phase(
        "generate",
        [
            (f"gen:{seed}", [*base, f"gen:{seed}"], [f"data/telemetry_seed{seed}.npz"])
            for seed in SEEDS
        ],
        args.max_workers,
        args.run_root,
        manifest,
        manifest_path,
        published,
    )
    phase(
        "features",
        [
            (f"feat:{seed}", [*base, f"feat:{seed}"], [f"ckpt/feat_seed{seed}.npz"])
            for seed in SEEDS
        ],
        args.max_workers,
        args.run_root,
        manifest,
        manifest_path,
        published,
    )
    phase(
        "models",
        [
            (
                f"model:{seed}:{model}",
                [*base, f"model:{seed}:{model}"],
                [f"ckpt/model_seed{seed}_{model}.npz", f"raw/model_seed{seed}_{model}.json"],
            )
            for seed in SEEDS
            for model in MODELS
        ],
        args.max_workers,
        args.run_root,
        manifest,
        manifest_path,
        published,
    )
    phase(
        "cross",
        [
            (f"cross:{seed}", [*base, f"cross:{seed}"], [f"raw/cross_seed{seed}.json"])
            for seed in SEEDS
        ],
        args.max_workers,
        args.run_root,
        manifest,
        manifest_path,
        published,
    )

    subprocess.run(
        [
            python,
            str(analysis),
            "property",
            "--run-root",
            str(args.run_root),
            "--seeds",
            "10-29",
            "--models",
            ",".join(MODELS),
            "--model-seeds",
            "10-29",
            "--expected-amplitude-scale",
            "1.0",
        ],
        check=True,
    )
    register_tree(args.run_root, "metrics", manifest, manifest_path, published)
    manifest["status"] = "PROPERTY_PASS"
    atomic_json(manifest_path, manifest)

    for position, seed in enumerate(SEEDS, 1):
        subprocess.run(
            [
                python,
                str(analysis),
                "analyze",
                "--run-root",
                str(args.run_root),
                "--seeds",
                str(seed),
                "--null-draws",
                str(NULL_DRAWS),
            ],
            check=True,
        )
        register_file(
            args.run_root,
            f"analysis_ckpt/seed{seed}.json",
            manifest,
            manifest_path,
            published,
        )
        register_tree(args.run_root, "metrics", manifest, manifest_path, published)
        print(
            f"CONFIRM_V4_HEARTBEAT phase=analysis completed={position}/{len(SEEDS)} "
            f"seed={seed}",
            flush=True,
        )

    subprocess.run(
        [
            python,
            str(analysis),
            "analyze",
            "--run-root",
            str(args.run_root),
            "--seeds",
            "10-29",
            "--null-draws",
            str(NULL_DRAWS),
        ],
        check=True,
    )
    register_tree(args.run_root, "metrics", manifest, manifest_path, published)
    manifest["status"] = "ANALYSIS_COMPLETE"
    atomic_json(manifest_path, manifest)

    completed = subprocess.run(
        [
            python,
            str(confirm),
            "--run-root",
            str(args.run_root),
            "--release-root",
            str(args.release_root),
            "--release-tag",
            TAG,
            "--release-commit",
            commit,
        ]
    )
    register_tree(args.run_root, "metrics", manifest, manifest_path, published)
    manifest["status"] = "CONFIRMED" if completed.returncode == 0 else "NOT_CONFIRMED"
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    atomic_json(manifest_path, manifest)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()

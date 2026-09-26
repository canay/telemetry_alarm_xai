"""Derive per-unit timeouts from MEASURED unit durations and write the Section 10 preflight fields.

Operation: f07-rb4-esa-adb-revision-20260926
Reads only unit status lines with elapsed seconds: the real run's logs/units.jsonl (prep, stdz on the
full data) and the PT1 smoke CLI transcript property_tests/pt1_cli.log (fit, episodes, attr_episode on
the bounded subset). The PT1 checkpoint JSON files and work files stay quarantined and are not opened;
no score, flag, threshold or episode count is read. Writes TIMEOUTS.json and EXPERIMENT_PLAN_SECTION10.json.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
MARGIN = 3.0
# scale factors from the smoke subset to the full data, fixed from the design (not from any outcome):
# fit: N_fit 100,000 vs 20,000 (x5) plus scoring of about 1.52 M vs 0.157 M validation+test windows (x10);
# episodes: test windows 7 years vs 6 months (x14); attr_episode: episode count scales with test length
# (x14) and the model-call part is capped at 20,000 episodes.
SCALE = {"fit": 10.0, "episodes": 14.0, "attr_episode": 14.0}
FLOOR_S = {"prep": 15 * 60, "stdz": 60 * 60, "fit": 30 * 60, "episodes": 30 * 60, "attr_episode": 60 * 60,
           "eval": 240 * 60, "decision": 30 * 60}
CEIL_S = {"attr_episode": 6 * 3600, "fit": 4 * 3600, "episodes": 2 * 3600}


def rows(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("status") == "completed" and "elapsed_seconds" in r:
            out.append({"unit": r["unit"], "elapsed": float(r["elapsed_seconds"])})
    return out


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def main() -> int:
    real = rows(RUN / "logs" / "units.jsonl")
    smoke = rows(RUN / "property_tests" / "pt1_cli.log")
    assert real and smoke, "TOOL FAULT: no completed unit rows found"
    by = {}
    for src, rs in (("full", real), ("smoke", smoke)):
        for r in rs:
            prefix = r["unit"].split(":")[0]
            by.setdefault((src, prefix), []).append(r["elapsed"])
    assert ("full", "prep") in by and ("smoke", "fit") in by, "TOOL FAULT: expected unit classes missing"
    measured = {f"{s}:{p}": {"n": len(v), "max_s": round(max(v), 2), "median_s": round(sorted(v)[len(v) // 2], 2)}
                for (s, p), v in sorted(by.items())}
    timeouts = {}
    basis = {}
    for prefix in ("prep", "stdz"):
        mx = max(by[("full", prefix)])
        timeouts[prefix] = int(max(FLOOR_S[prefix], math.ceil(MARGIN * mx)))
        basis[prefix] = f"full-data max {mx:.1f} s x margin {MARGIN} (floor {FLOOR_S[prefix]} s)"
    for prefix in ("fit", "episodes", "attr_episode"):
        mx = max(by[("smoke", prefix)])
        val = max(FLOOR_S[prefix], math.ceil(MARGIN * SCALE[prefix] * mx))
        val = min(val, CEIL_S[prefix])
        timeouts[prefix] = int(val)
        basis[prefix] = (f"smoke max {mx:.1f} s x scale {SCALE[prefix]} x margin {MARGIN} "
                         f"(floor {FLOOR_S[prefix]} s, ceiling {CEIL_S[prefix]} s)")
    timeouts["eval"] = FLOOR_S["eval"]
    timeouts["decision"] = FLOOR_S["decision"]
    basis["eval"] = "no smoke measurement (the eval unit opens test labels); fixed 240 min with heartbeat"
    basis["decision"] = "fixed 30 min"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    (RUN / "TIMEOUTS.json").write_bytes(json.dumps({"at": now, "operation_id": "f07-rb4-esa-adb-revision-20260926",
                                                    "timeouts_s": timeouts, "basis": basis, "measured": measured},
                                                   indent=1).encode("utf-8"))
    import shutil

    import psutil

    vm = psutil.virtual_memory()
    du = shutil.disk_usage("C:/")  # psutil.disk_usage fails on this host (SystemError bad format char)
    status = json.loads((RUN / "run_status.json").read_text(encoding="utf-8"))
    sec10 = {
        "at": now, "tool": "Cowork-Claude", "model": "claude-opus-5-5", "operation_id": "f07-rb4-esa-adb-revision-20260926",
        "owner": "EXPERIMENT_DURABILITY_AND_RECOVERY.md section 10",
        "atomic_unit": "prep:<channel> (58), stdz:<set> (2), fit:<set>:<model>:<rep> (36), episodes:<set>:<model> (12), attr_episode:<set>:<model>:<rep> (36), eval:<set> (2), decision (1)",
        "planned_unit_count": 147,
        "checkpoint_path_and_schema": "RUN/units/<unit_id with ':' -> '__'>.json: unit_id, attempt_id, status=completed, started_at, ended_at, elapsed_seconds, outputs[{path, bytes, sha256}], code_sha256{file: sha256}, host, extra",
        "atomic_write_strategy": "every output is written to a .tmp sibling and os.replace()d; the checkpoint JSON is written last, atomically",
        "resume_command": "python RUN/src/esa_arm.py run  (under controlled_exit_supervisor.py for restarts)",
        "resume_validation_rule": "a unit is skipped (skipped_validated) only if its checkpoint status is completed and every recorded output exists with the recorded size and SHA-256; otherwise existing outputs are moved to C:/ESA_ADB_RAW/work/arm/quarantine/<unit>_<id> and the unit reruns under a new attempt id",
        "interruption_smoke_evidence": "v3 code on the real prep units: controlled stop after two units (exit 75, CONTROLLED_STOP, marker logs/controlled_stop_v3.marker), supervisor restart, skipped_validated for the two units, completion; transcript logs/prefreeze_cli.log, unit log logs/units.jsonl, terminal status run_status.json (final: " + str(status.get("status")) + "/" + str(status.get("exit_code")) + "); the v2-code smoke of 2026-09-26 11:21-11:28Z is kept in durability_smoke_v2code/",
        "per_unit_timeout": {"source": "RUN/TIMEOUTS.json", "timeouts_s": timeouts, "basis": basis},
        "whole_run_watchdog": "16 h from runner start (esa_arm.Config.whole_run_timeout_s), enforced by the heartbeat thread (terminal TIMED_OUT, exit 124)",
        "eta_basis_and_margin": "prep and stdz measured on the full data; fit, episodes and attr_episode measured on the PT1 smoke and scaled by the design ratios in TIMEOUTS.json basis; expected wall-clock for the post-freeze units 3-8 h on this host, margin 3 on every unit timeout",
        "max_workers_and_thread_limits": "one worker process; OMP_NUM_THREADS = OPENBLAS_NUM_THREADS = MKL_NUM_THREADS = 2; torch one thread",
        "disk_ram_resource_preflight": {"measured_at": now, "available_ram_mb": round(vm.available / 2 ** 20), "total_ram_mb": round(vm.total / 2 ** 20),
                                        "free_disk_gb_C": round(du.free / 2 ** 30, 1),
                                        "unit_start_rule": "wait up to 20 min for available RAM >= 700 MB, then stop; stop when free disk < 5 GB"},
        "progress_heartbeat_path_and_stall_threshold": "RUN/heartbeat.json (atomic) and RUN/logs/progress.jsonl (append); stall = 3 missed heartbeats (180 s)",
        "heartbeat_cadence_schema_writer_and_atomicity": "60 s, background thread in the worker; fields run_id, unit_id, attempt_id, pid, phase, phase_started_at, unit_elapsed_seconds, completed_atomic_units, planned_atomic_units, last_durable_checkpoint_at, process_cpu_seconds, run_elapsed_seconds, rss_mb, available_mb; atomic_json (tmp + os.replace)",
        "heartbeat_advancement_smoke_evidence": "logs/progress.jsonl rows of the pre-freeze run advance in timestamp, completed_atomic_units and phase",
        "opaque_phase_supervisor_sampling_rule": "no opaque phase: every long loop updates the phase (batch index) and the heartbeat thread samples the worker's own PID; the controlled-exit supervisor only interprets exit code plus run_status.json",
        "opaque_runtime_bound_admission": "mode=heartbeat; threshold_seconds=300; evidence=RUN/logs/progress.jsonl; overrun=heartbeat_or_fail_closed",
        "raw_output_contract": "C:/ESA_ADB_RAW/work/arm/<set>/{Z.f32, stale.f32, meta.npz, stats.json, braw/, fits/, episodes/, attr/, eval/} and RUN/results/<set>/*.csv, RUN/results/DECISION_H_E1.json; every output hash-recorded in its unit checkpoint",
        "aggregate_script_and_inputs": "eval:<set> and decision units read only saved unit outputs (scores, episodes, masses) plus the label table; no model refit",
        "plot_script_and_inputs": "manuscript figures and tables are produced by a separate script from RUN/results CSV/JSON only; plotting never reruns a model",
        "decision_artifact_path_and_criterion_schema": "RUN/results/DECISION_H_E1.json: per detector n, status, assay statistic and bound, D, primary LB, Student-t LB, pass flags, seeds; k, required passes, verdict, Student-t sensitivity",
        "decision_discriminator_statistics_persisted": True,
        "notification_lifecycle": "no Telegram hook on this host; terminal statuses COMPLETED/FAILED/TIMED_OUT/CONTROLLED_STOP are written to run_status.json on every path",
        "terminal_status_paths": ["RUN/run_status.json", "RUN/logs/units.jsonl", "RUN/logs/prefreeze_cli.log and the post-freeze CLI transcript"],
        "predecessor_terminal_status_poll_rule": "the post-freeze launch requires run_status.json COMPLETED/0 from the pre-freeze run and the verified public-freeze record",
        "container_image_layer_budget": "not applicable: no container; local Python environment",
        "phased_engine_schedule_rule": "not applicable: single local worker, no image pulls; disk threshold 5 GB free stops the run",
        "recovery_merge_equivalence_gate": "not applicable: no partial-run merge; validated resume reruns incomplete units in place",
        "code_snapshot_path_and_sha256": "RUN/code_snapshot/ with SHA-256 per file, copied at the freeze; the freeze record names the same hashes and esa_arm.assert_frozen refuses a fit when the executing code differs",
        "local_delivery_and_verification_rule": "local run: outputs are written in place; completeness is verified by checkpoint validation of every planned unit and by the independent recomputation's verified_artifacts binding",
        "partial_result_promotion_policy": "prohibited",
        "smoke_duration_reading_note": "only unit durations were read from the PT1 transcript; PT1 checkpoints, logs and work files remain quarantined until the freeze",
        "inputs_sha256": {"logs/units.jsonl": sha(RUN / "logs" / "units.jsonl"), "property_tests/pt1_cli.log": sha(RUN / "property_tests" / "pt1_cli.log")},
    }
    (RUN / "EXPERIMENT_PLAN_SECTION10.json").write_bytes(json.dumps(sec10, indent=1).encode("utf-8"))
    print(json.dumps({"timeouts_s": timeouts, "measured": measured}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Reproduction Guide

Date/time: 2026-08-26 17:57 +03:00  
Tool: Codex  
Model: GPT-5  
Operation ID: `f07-criticality-v4-pre-freeze-repair-20260826`

## Environment

The primary recorded environment used Python 3.12.12. Create an isolated environment and install the recorded dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On PowerShell, activate with `.\.venv\Scripts\Activate.ps1`.

## Deterministic synthetic experiment

Run commands from `code/` because the original scripts deliberately resolve `../data`, `../ckpt`, and `../results` relative to that directory.

```bash
mkdir -p ../data ../ckpt ../results
for seed in 0 1 2 3 4; do python telemetry_generator.py "$seed"; done
MAX_SEC=3600 bash driver.sh
python aggregate.py
python q1_audit_revision_stats.py
python q1_audit_label_budget.py
```

`driver.sh` is resumable. Repeat it until it prints `ALLDONE`; completed work units are retained under `ckpt/`.

The ten-seed sensitivity layer uses seeds 0–9. Generate the additional seeds with `telemetry_generator.py`, run the corresponding work units with `run_unit.py`, and then execute:

```bash
python q1_audit_revision_stats.py --seeds 0-9 --out-dir ../results/q1_seed_expansion
```

## Public-frozen V4 confirmation

`PROTOCOL_V1_1.md` and `CONFIRMATORY_PLAN.json` are the controlling records.
Do not generate seeds 10--29 before the GitHub `v1.1.0` release is published.
After publication, use a new or empty output directory outside the repository:

```bash
python code/run_confirmation_v4.py \
  --release-root . \
  --run-root ../criticality_confirmation_v4 \
  --max-workers 2
```

The driver is intentionally fail-closed. It dereferences the remote tag through
both Git and the GitHub API, verifies the plan hash published in the release
body, pins amplitude scale `1.0`, registers every resumable artifact, and runs
property, null, analysis, and five-endpoint decision gates. Reusing a partial
unregistered run is forbidden; start a distinct empty run directory instead.

## External transfer checks

OpenML 40900 is fetched through the OpenML/scikit-learn path used by `run_openml.py`. KDDCup99 is fetched by `sklearn.datasets.fetch_kddcup99` when `run_second_transfer_benchmark.py` is executed.

For OPSSAT-AD, download `dataset.csv` from the source record identified by DOI `10.5281/zenodo.12588359`, place it at `data/external/opssat/dataset.csv`, and run from the repository root:

```bash
python code/run_opssat_transfer_benchmark.py --base-dir . --n-jobs 2
```

The external datasets are not included in this repository. Their source records govern access and reuse.

## Verification boundaries

The legacy `results/` files support the earlier evidence layers. Files prefixed
`v3_discovery_` are exploratory design evidence only. Release `v1.1.0` contains
no seed 10--29 outcomes by construction. Do not interpret OpenML, KDDCup99, or
OPSSAT-AD as evidence of causal spacecraft fault-channel attribution or live
operational validation.

# Dataset Acquisition and Boundaries

Date/time: 2026-08-21 16:37 +03:00  
Tool: Codex  
Model: GPT-5.6  
Operation ID: `f07-public-release-g11a-20260821`

No third-party dataset or generated cache is bundled in this repository.

- Synthetic telemetry is generated deterministically by `code/telemetry_generator.py` with fixed integer seeds.
- OpenML dataset 40900 is obtained through the OpenML/scikit-learn access path used by `code/run_openml.py`.
- KDDCup99 is fetched by `sklearn.datasets.fetch_kddcup99` in `code/run_second_transfer_benchmark.py`.
- OPSSAT-AD `dataset.csv` is obtained from DOI `10.5281/zenodo.12588359` and placed at `data/external/opssat/dataset.csv` before running the corresponding script.

Each external dataset remains subject to its source record and reuse terms. The repository's MIT License applies only to the original code and documentation distributed here.

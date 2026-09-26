"""F3 schema inspection for the ESA-ADB Mission1 bounded arm (NO model fit).

Reads the verified Mission1 archive, records archive hashes, member inventory,
metadata tables, label-schema facts (category counts, affected-channel set
sizes, official split membership) and per-channel sampling statistics.  It
opens no model, computes no detector score and no explanation, and writes no
performance number.  Label reading is limited to schema and counts, which the
protocol candidate (Section 3, F3) lists as pre-freeze facts.

Operation: f07-rb4-esa-adb-revision-20260926
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import sys
import time
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

EXPECTED_SIZE = 3_776_246_073
EXPECTED_MD5 = "9770ad12ed730238f37c42d5c27ab436"
TEST_SPLIT = pd.Timestamp("2007-01-01")
VALIDATION_START = pd.Timestamp("2006-10-01")
LIGHTWEIGHT = [f"channel_{i}" for i in range(41, 47)]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def file_hashes(path: Path) -> dict:
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            md5.update(block)
            sha.update(block)
            size += len(block)
    return {"size_bytes": size, "md5": md5.hexdigest(), "sha256": sha.hexdigest()}


def log(stream, **row) -> None:
    row = {"at": now(), **row}
    stream.write(json.dumps(row) + "\n")
    stream.flush()
    print(json.dumps(row), flush=True)


def read_member_bytes(archive: zipfile.ZipFile, name: str, meta_dir: Path | None) -> bytes:
    """Read a member; Deflate64 members (type 9) come from a 7-Zip extraction.

    Python's zipfile cannot decode Deflate64, so such members are extracted
    beforehand with 7-Zip into ``meta_dir`` and accepted only when their CRC32
    and size equal the archive's own central-directory record.
    """
    info = archive.getinfo(name)
    if info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        return archive.read(name)
    assert meta_dir is not None, f"member {name} needs --meta-dir (compress_type {info.compress_type})"
    extracted = meta_dir / Path(name).name
    blob = extracted.read_bytes()
    assert len(blob) == info.file_size, (name, len(blob), info.file_size)
    assert (zlib.crc32(blob) & 0xFFFFFFFF) == info.CRC, (name, "CRC32 mismatch")
    return blob


def read_member_csv(archive: zipfile.ZipFile, name: str, meta_dir: Path | None) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(read_member_bytes(archive, name, meta_dir)))


def load_channel(archive: zipfile.ZipFile, member: str) -> pd.DataFrame:
    """Channel members are ZIP-compressed pickles holding one DataFrame."""
    blob = archive.read(member)
    with zipfile.ZipFile(io.BytesIO(blob)) as inner:
        names = inner.namelist()
        assert len(names) == 1, (member, names)
        with inner.open(names[0]) as handle:
            frame = pd.read_pickle(io.BytesIO(handle.read()))
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--meta-dir", default=None)
    args = parser.parse_args()
    archive_path = Path(args.zip)
    meta_dir = Path(args.meta_dir) if args.meta_dir else None
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (out / "F3_PROGRESS.jsonl").open("a", encoding="utf-8") as progress:
        log(progress, phase="hash_start", path=str(archive_path))
        hashes = file_hashes(archive_path)
        log(progress, phase="hash_done", **hashes)
        if hashes["size_bytes"] != EXPECTED_SIZE or hashes["md5"] != EXPECTED_MD5:
            log(progress, phase="STOP_MD5_OR_SIZE_MISMATCH")
            return 3
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            inventory = [
                {"name": i.filename, "file_size": i.file_size, "compress_size": i.compress_size}
                for i in infos
            ]
            names = [i["name"] for i in inventory]
            assert len(names) == len(set(names)), "duplicate archive member names"
            atomic_text(out / "ARCHIVE_INVENTORY.json", json.dumps(inventory, indent=1))

            def find(suffix: str) -> str | None:
                hits = [n for n in names if n.replace("\\", "/").endswith(suffix)]
                assert len(hits) <= 1, (suffix, hits)
                return hits[0] if hits else None

            meta_names = {
                key: find(key)
                for key in ("labels.csv", "anomaly_types.csv", "channels.csv", "telecommands.csv", "events.csv")
            }
            log(progress, phase="metadata_members", **{k: v for k, v in meta_names.items()})
            tables = {}
            for key, member in meta_names.items():
                if member is None:
                    continue
                frame = read_member_csv(archive, member, meta_dir)
                tables[key] = frame
                frame.to_csv(out / f"meta_{key}", index=False)
            channels = tables["channels.csv"]
            labels = tables["labels.csv"]
            types = tables["anomaly_types.csv"]

            facts: dict = {
                "created_at_utc": now(),
                "host": platform.node(),
                "python": sys.version.split()[0],
                "pandas": pd.__version__,
                "numpy": np.__version__,
                "archive": {"path": str(archive_path), **hashes, "member_count": len(names)},
                "channels_columns": list(channels.columns),
                "labels_columns": list(labels.columns),
                "anomaly_types_columns": list(types.columns),
                "channel_count": int(len(channels)),
            }
            target_col = [c for c in channels.columns if c.lower() == "target"]
            facts["target_column"] = target_col
            if target_col:
                tv = channels[target_col[0]].astype(str).str.strip().str.upper()
                facts["target_value_counts"] = tv.value_counts().to_dict()
                target_channels = sorted(
                    channels.loc[tv.isin(["YES", "TRUE", "1"]), "Channel"].astype(str).tolist(),
                    key=lambda s: int(s.split("_")[-1]) if s.split("_")[-1].isdigit() else s,
                )
            else:
                target_channels = []
            facts["target_channels"] = target_channels
            facts["target_channel_count"] = len(target_channels)
            facts["lightweight_channels"] = LIGHTWEIGHT
            facts["lightweight_all_target"] = all(c in target_channels for c in LIGHTWEIGHT)

            lab = labels.copy()
            lab["StartTime"] = pd.to_datetime(lab["StartTime"], utc=True).dt.tz_localize(None)
            lab["EndTime"] = pd.to_datetime(lab["EndTime"], utc=True).dt.tz_localize(None)
            cat_col = [c for c in types.columns if c.lower() == "category"]
            facts["category_column"] = cat_col
            merged = lab.merge(types[["ID", cat_col[0]]], on="ID", how="left")
            merged = merged.rename(columns={cat_col[0]: "Category"})
            facts["label_rows"] = int(len(merged))
            facts["label_rows_without_category"] = int(merged["Category"].isna().sum())
            facts["categories_in_types"] = types[cat_col[0]].value_counts().to_dict()
            per_event = merged.groupby("ID").agg(
                category=("Category", "first"),
                start=("StartTime", "min"),
                end=("EndTime", "max"),
                n_channels=("Channel", "nunique"),
            )
            target_set = set(target_channels)
            target_rows = merged[merged["Channel"].astype(str).isin(target_set)]
            per_event["n_target_channels"] = (
                target_rows.groupby("ID")["Channel"].nunique().reindex(per_event.index).fillna(0).astype(int)
            )
            light_rows = merged[merged["Channel"].astype(str).isin(set(LIGHTWEIGHT))]
            per_event["n_lightweight_channels"] = (
                light_rows.groupby("ID")["Channel"].nunique().reindex(per_event.index).fillna(0).astype(int)
            )

            def split_of(row) -> str:
                if row["end"] < VALIDATION_START:
                    return "fit"
                if row["start"] >= TEST_SPLIT:
                    return "test"
                if row["end"] < TEST_SPLIT and row["start"] >= VALIDATION_START:
                    return "validation"
                return "boundary_spanning"

            per_event["split"] = per_event.apply(split_of, axis=1)
            per_event.to_csv(out / "event_schema_table.csv")
            facts["events_total"] = int(len(per_event))
            facts["events_by_category"] = per_event["category"].value_counts().to_dict()
            facts["events_by_split_and_category"] = {
                f"{s}|{c}": int(n)
                for (s, c), n in per_event.groupby(["split", "category"]).size().items()
            }
            test_events = per_event[per_event["split"] == "test"]
            scored = test_events[
                test_events["category"].isin(["Anomaly", "Rare Event"]) & (test_events["n_target_channels"] > 0)
            ]
            facts["test_scoreable_events_anomaly_plus_rare"] = int(len(scored))
            facts["test_scoreable_anomalies"] = int((scored["category"] == "Anomaly").sum())
            facts["test_scoreable_rare_events"] = int((scored["category"] == "Rare Event").sum())
            facts["test_affected_target_set_size_distribution"] = (
                scored["n_target_channels"].value_counts().sort_index().to_dict()
            )
            facts["test_lightweight_scoreable_events"] = int((scored["n_lightweight_channels"] > 0).sum())
            facts["label_time_range"] = [str(merged["StartTime"].min()), str(merged["EndTime"].max())]
            log(progress, phase="labels_done", events=facts["events_total"])

            channel_members = sorted(
                [n for n in names if "/channels/" in n.replace("\\", "/") and n.endswith(".zip")]
            )
            facts["channel_member_count"] = len(channel_members)
            sampling = []
            for index, member in enumerate(channel_members):
                t0 = time.monotonic()
                frame = load_channel(archive, member)
                name = Path(member).stem
                idx = pd.DatetimeIndex(frame.index)
                if idx.tz is not None:
                    idx = idx.tz_convert(None)
                diffs = np.diff(idx.asi8) / 1e9 if len(idx) > 1 else np.array([])
                values = np.asarray(frame.iloc[:, 0])
                sampling.append(
                    {
                        "channel": name,
                        "is_target": name in target_set,
                        "n_samples": int(len(frame)),
                        "first": str(idx.min()),
                        "last": str(idx.max()),
                        "monotonic_increasing": bool(idx.is_monotonic_increasing),
                        "duplicate_timestamps": int(idx.duplicated().sum()),
                        "median_interval_s": float(np.median(diffs)) if len(diffs) else None,
                        "p90_interval_s": float(np.percentile(diffs, 90)) if len(diffs) else None,
                        "max_interval_s": float(np.max(diffs)) if len(diffs) else None,
                        "share_intervals_gt_30s": float(np.mean(diffs > 30.0)) if len(diffs) else None,
                        "value_dtype": str(values.dtype),
                        "n_nonfinite": int((~np.isfinite(values.astype(float))).sum()),
                        "n_before_test_split": int((idx < TEST_SPLIT).sum()),
                        "column_name": str(frame.columns[0]),
                    }
                )
                del frame, values, idx, diffs
                log(progress, phase="channel", index=index + 1, of=len(channel_members), channel=name,
                    seconds=round(time.monotonic() - t0, 2))
            pd.DataFrame(sampling).to_csv(out / "channel_sampling.csv", index=False)
            facts["elapsed_seconds"] = round(time.monotonic() - started, 1)
            atomic_text(out / "F3_FACTS.json", json.dumps(facts, indent=2, default=str))
            log(progress, phase="F3_COMPLETE", elapsed_seconds=facts["elapsed_seconds"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

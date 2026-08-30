"""Regenerate the public package SHA-256 inventory from Git-visible files.

Operation: f07-v5-round-d-final-corrections-20260830
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "checksums.sha256"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    visible = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        text=True,
        encoding="utf-8",
    ).splitlines()
    files = sorted(
        relative.replace("\\", "/")
        for relative in visible
        if relative.replace("\\", "/") != OUTPUT.name
        and (ROOT / relative).is_file()
    )
    lines = [f"{sha256(ROOT / relative)}  {relative}" for relative in files]
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, OUTPUT)
    print(f"CHECKSUMS_WRITTEN files={len(files)} output={OUTPUT}")


if __name__ == "__main__":
    main()

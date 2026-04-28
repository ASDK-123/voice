from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists() and src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def export_bundle(output_zip: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="cosyvoice_diag_") as td:
        tmp = Path(td)
        _copy_if_exists(ROOT / "app_config.json", tmp / "app_config.json")
        _copy_if_exists(ROOT / "data" / "logs" / "app.log", tmp / "logs" / "app.log")
        _copy_if_exists(ROOT / "data" / "logs" / "access.jsonl", tmp / "logs" / "access.jsonl")
        _copy_if_exists(ROOT / "data" / "logs" / "crash.log", tmp / "logs" / "crash.log")

        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in tmp.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(tmp).as_posix())
    return output_zip


def main() -> int:
    parser = argparse.ArgumentParser(description="Export CosyVoice diagnostic bundle")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="output zip path (default: data/logs/diag_YYYYmmdd_HHMMSS.zip)",
    )
    args = parser.parse_args()

    if args.output:
        out = Path(args.output).resolve()
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = (ROOT / "data" / "logs" / f"diag_{ts}.zip").resolve()

    result = export_bundle(out)
    print(f"diagnostic bundle exported: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


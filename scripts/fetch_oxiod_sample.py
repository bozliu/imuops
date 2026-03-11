#!/usr/bin/env python3
"""Download or unpack an OxIOD sample without vendoring the dataset."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Direct URL to an OxIOD sample zip.")
    parser.add_argument("--zip-path", type=Path, help="Local OxIOD sample zip.")
    parser.add_argument("--out", type=Path, required=True, help="Extraction directory.")
    args = parser.parse_args()
    if not args.url and not args.zip_path:
        parser.error("Either --url or --zip-path is required.")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.zip_path:
        archive = args.zip_path
    else:
        archive = Path(tempfile.gettempdir()) / "oxiod_sample.zip"
        with requests.get(args.url, timeout=120, stream=True) as response:
            response.raise_for_status()
            with archive.open("wb") as handle:
                shutil.copyfileobj(response.raw, handle)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(args.out)
    print(f"Extracted OxIOD sample to {args.out}")


if __name__ == "__main__":
    main()


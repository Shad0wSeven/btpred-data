#!/usr/bin/env python3
"""Download the granular Binance datasets selected for this repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

BASE_URL = "https://data.binance.vision/data"
SPOT_MONTHS = ("2026-04", "2026-05", "2026-06")
SPOT_DAYS = tuple(f"2026-07-{day:02d}" for day in range(1, 28))
DEPTH_DAYS = tuple(f"2026-07-{day:02d}" for day in range(1, 28))


def selected_files(root: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for date in SPOT_MONTHS:
        name = f"BTCFDUSD-trades-{date}.zip"
        files.append(
            (
                f"{BASE_URL}/spot/monthly/trades/BTCFDUSD/{name}",
                root / "granular" / "spot_raw_trades" / name,
            )
        )
    for date in SPOT_DAYS:
        name = f"BTCFDUSD-trades-{date}.zip"
        files.append(
            (
                f"{BASE_URL}/spot/daily/trades/BTCFDUSD/{name}",
                root / "granular" / "spot_raw_trades" / name,
            )
        )
    for date in DEPTH_DAYS:
        name = f"BTCUSDT-bookDepth-{date}.zip"
        files.append(
            (
                f"{BASE_URL}/futures/um/daily/bookDepth/BTCUSDT/{name}",
                root / "granular" / "futures_um_book_depth" / name,
            )
        )
    return files


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def official_sha256(url: str) -> str:
    request = urllib.request.Request(
        f"{url}.CHECKSUM", headers={"User-Agent": "btpred-data/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode().split()[0]


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "btpred-data/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as sink:
        while block := response.read(1024 * 1024):
            sink.write(block)
    partial.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    parser.add_argument(
        "--force", action="store_true", help="redownload files already present"
    )
    args = parser.parse_args()

    manifest: list[dict[str, object]] = []
    files = selected_files(args.root)
    for index, (url, destination) in enumerate(files, 1):
        if args.force or not destination.exists():
            print(f"[{index:02d}/{len(files)}] {destination.name}")
            download(url, destination)
        with zipfile.ZipFile(destination) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"CRC failure in {destination}: {bad_member}")
            members = archive.namelist()
        local_digest = sha256(destination)
        upstream_digest = official_sha256(url)
        if local_digest != upstream_digest:
            raise RuntimeError(
                f"SHA-256 mismatch for {destination}: "
                f"{local_digest} != {upstream_digest}"
            )
        manifest.append(
            {
                "path": str(destination.relative_to(args.root)),
                "source_url": url,
                "bytes": destination.stat().st_size,
                "sha256": local_digest,
                "binance_checksum_verified": True,
                "members": members,
            }
        )

    manifest_path = args.root / "granular" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {manifest_path} with {len(manifest)} verified archives")


if __name__ == "__main__":
    main()

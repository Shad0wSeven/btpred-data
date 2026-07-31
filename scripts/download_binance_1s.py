#!/usr/bin/env python3
"""Download and verify dense native Binance BTCFDUSD one-second klines."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://data.binance.vision/data/spot"
MONTHS = tuple(f"2026-{month:02d}" for month in range(1, 7))
DAYS = tuple(f"2026-07-{day:02d}" for day in range(1, 30))


def selected_files(root: Path) -> list[tuple[str, Path, datetime, datetime]]:
    files: list[tuple[str, Path, datetime, datetime]] = []
    output = root / "spot_1s"
    for month in MONTHS:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        name = f"BTCFDUSD-1s-{month}.zip"
        files.append(
            (
                f"{BASE_URL}/monthly/klines/BTCFDUSD/1s/{name}",
                output / name,
                start,
                end,
            )
        )
    for day_text in DAYS:
        day = date.fromisoformat(day_text)
        start = datetime.combine(day, datetime.min.time(), timezone.utc)
        end = start + timedelta(days=1)
        name = f"BTCFDUSD-1s-{day_text}.zip"
        files.append(
            (
                f"{BASE_URL}/daily/klines/BTCFDUSD/1s/{name}",
                output / name,
                start,
                end,
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


def download(url: str, destination: Path, force: bool) -> None:
    if destination.exists() and not force:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "btpred-data/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, partial.open(
        "wb"
    ) as sink:
        while block := response.read(1024 * 1024):
            sink.write(block)
    partial.replace(destination)


def inspect_archive(path: Path, start: datetime, end: datetime) -> dict[str, object]:
    expected_first = int(start.timestamp())
    expected_last = int(end.timestamp()) - 1
    expected_rows = expected_last - expected_first + 1
    rows = gaps = duplicates = zero_trade_rows = total_trades = 0
    first_second = last_second = previous = None

    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"CRC failure in {path}: {bad_member}")
        members = archive.namelist()
        if len(members) != 1:
            raise RuntimeError(f"expected one CSV in {path}, found {members}")
        with archive.open(members[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            for row in csv.reader(text):
                if len(row) != 12:
                    raise RuntimeError(f"expected 12 columns in {path}: {row[:3]}")
                timestamp = int(row[0])
                second = timestamp // 1_000_000
                if first_second is None:
                    first_second = second
                if previous is not None:
                    delta = second - previous
                    if delta > 1:
                        gaps += delta - 1
                    elif delta <= 0:
                        duplicates += 1
                previous = last_second = second
                trades = int(row[8])
                total_trades += trades
                zero_trade_rows += trades == 0
                rows += 1

    if (
        rows != expected_rows
        or first_second != expected_first
        or last_second != expected_last
        or gaps
        or duplicates
    ):
        raise RuntimeError(
            f"{path} is not a dense one-second series: rows={rows}/"
            f"{expected_rows}, first={first_second}/{expected_first}, "
            f"last={last_second}/{expected_last}, gaps={gaps}, "
            f"duplicates={duplicates}"
        )
    return {
        "member": members[0],
        "rows": rows,
        "first_open_time_utc": start.isoformat(),
        "last_open_time_utc": datetime.fromtimestamp(
            expected_last, timezone.utc
        ).isoformat(),
        "missing_seconds": gaps,
        "duplicate_seconds": duplicates,
        "zero_trade_rows": zero_trade_rows,
        "total_trades": total_trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    files = selected_files(args.root)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(download, url, path, args.force): (index, path)
            for index, (url, path, _, _) in enumerate(files, 1)
        }
        for future in as_completed(futures):
            index, path = futures[future]
            future.result()
            print(f"downloaded {index:02d}/{len(files)} {path.name}")

    manifest_files = []
    for index, (url, path, start, end) in enumerate(files, 1):
        local_digest = sha256(path)
        upstream_digest = official_sha256(url)
        if local_digest != upstream_digest:
            raise RuntimeError(
                f"SHA-256 mismatch for {path}: "
                f"{local_digest} != {upstream_digest}"
            )
        inspection = inspect_archive(path, start, end)
        manifest_files.append(
            {
                "path": str(path.relative_to(args.root)),
                "source_url": url,
                "bytes": path.stat().st_size,
                "sha256": local_digest,
                "binance_checksum_verified": True,
                **inspection,
            }
        )
        print(
            f"verified {index:02d}/{len(files)} {path.name}: "
            f"{inspection['rows']} consecutive seconds"
        )

    manifest = {
        "symbol": "BTCFDUSD",
        "interval": "1s",
        "coverage_start_utc": manifest_files[0]["first_open_time_utc"],
        "coverage_end_utc": manifest_files[-1]["last_open_time_utc"],
        "archive_count": len(manifest_files),
        "row_count": sum(int(item["rows"]) for item in manifest_files),
        "compressed_bytes": sum(int(item["bytes"]) for item in manifest_files),
        "missing_seconds": sum(
            int(item["missing_seconds"]) for item in manifest_files
        ),
        "duplicate_seconds": sum(
            int(item["duplicate_seconds"]) for item in manifest_files
        ),
        "zero_trade_rows": sum(
            int(item["zero_trade_rows"]) for item in manifest_files
        ),
        "total_trades": sum(int(item["total_trades"]) for item in manifest_files),
        "files": manifest_files,
    }
    manifest_path = args.root / "spot_1s" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Wrote {manifest_path}: {manifest['row_count']} rows, "
        f"{manifest['missing_seconds']} missing seconds"
    )


if __name__ == "__main__":
    main()

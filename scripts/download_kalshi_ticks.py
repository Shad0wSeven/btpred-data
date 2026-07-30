#!/usr/bin/env python3
"""Download KXBTC15M trades and build dense one-second market panels."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"
RAW_FIELDS = (
    "created_time",
    "ticker",
    "trade_id",
    "count_fp",
    "yes_price_dollars",
    "no_price_dollars",
    "taker_outcome_side",
    "taker_book_side",
    "is_block_trade",
    "market_open_time",
    "market_close_time",
    "market_result",
)
SECOND_FIELDS = (
    "second_utc",
    "ticker",
    "seconds_to_close",
    "last_yes_price_dollars",
    "yes_open_dollars",
    "yes_high_dollars",
    "yes_low_dollars",
    "yes_close_dollars",
    "yes_vwap_dollars",
    "trade_count",
    "contracts_fp",
    "taker_yes_contracts_fp",
    "taker_no_contracts_fp",
    "market_result",
)
MARKET_FIELDS = (
    "ticker",
    "event_ticker",
    "open_time",
    "close_time",
    "settlement_ts",
    "result",
    "volume_fp",
    "open_interest_fp",
    "floor_strike",
    "cap_strike",
)


def request_json(path: str, params: dict[str, object], attempts: int = 9) -> dict:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "btpred-kalshi-ticks/1.0"}
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == attempts:
                raise
            retry_after = float(error.headers.get("Retry-After", 0) or 0)
            time.sleep(max(retry_after, min(20, 0.5 * 2**attempt)))
        except (TimeoutError, urllib.error.URLError):
            if attempt + 1 == attempts:
                raise
            time.sleep(min(20, 0.5 * 2**attempt))
    raise AssertionError("unreachable")


def parse_time(value: str) -> datetime:
    # Kalshi emits variable-width fractional seconds. Python 3.9's
    # fromisoformat does not accept every width, while strptime does.
    pattern = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)


def fetch_markets(start: datetime, end: datetime) -> list[dict]:
    markets: list[dict] = []
    cursor = ""
    while True:
        params: dict[str, object] = {
            "series_ticker": SERIES,
            "min_close_ts": int(start.timestamp()),
            "max_close_ts": int(end.timestamp()) - 1,
            "limit": 1000,
        }
        if cursor:
            params["cursor"] = cursor
        page = request_json("/markets", params)
        markets.extend(page.get("markets", []))
        cursor = page.get("cursor", "")
        if not cursor:
            break
    unique = {market["ticker"]: market for market in markets}
    return sorted(unique.values(), key=lambda market: market["close_time"])


def fetch_trades(ticker: str) -> list[dict]:
    trades: list[dict] = []
    cursor = ""
    while True:
        params: dict[str, object] = {"ticker": ticker, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        page = request_json("/markets/trades", params)
        trades.extend(page.get("trades", []))
        cursor = page.get("cursor", "")
        if not cursor:
            break
    unique = {trade["trade_id"]: trade for trade in trades}
    return sorted(
        unique.values(), key=lambda trade: (trade["created_time"], trade["trade_id"])
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decimal_sum(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0))


def write_market(
    raw_writer: csv.DictWriter,
    second_writer: csv.DictWriter,
    market: dict,
    trades: list[dict],
) -> tuple[int, int]:
    open_time = parse_time(market["open_time"])
    close_time = parse_time(market["close_time"])
    result = market.get("result", "")

    for trade in trades:
        raw_writer.writerow(
            {
                **{field: trade.get(field, "") for field in RAW_FIELDS},
                "market_open_time": market["open_time"],
                "market_close_time": market["close_time"],
                "market_result": result,
            }
        )

    by_second: dict[int, list[dict]] = defaultdict(list)
    for trade in trades:
        stamp = int(parse_time(trade["created_time"]).timestamp())
        if int(open_time.timestamp()) <= stamp < int(close_time.timestamp()):
            by_second[stamp].append(trade)

    last_price = ""
    second_rows = 0
    start_second = int(open_time.timestamp())
    close_second = int(close_time.timestamp())
    for stamp in range(start_second, close_second):
        ticks = by_second.get(stamp, [])
        prices = [Decimal(tick["yes_price_dollars"]) for tick in ticks]
        sizes = [Decimal(tick["count_fp"]) for tick in ticks]
        total = decimal_sum(sizes)
        yes_total = decimal_sum(
            [
                size
                for tick, size in zip(ticks, sizes)
                if tick.get("taker_outcome_side", tick.get("taker_side")) == "yes"
            ]
        )
        no_total = total - yes_total
        if ticks:
            last_price = str(prices[-1])
            vwap = str(
                sum((price * size for price, size in zip(prices, sizes)), Decimal(0))
                / total
            ) if total else ""
            price_values = {
                "yes_open_dollars": str(prices[0]),
                "yes_high_dollars": str(max(prices)),
                "yes_low_dollars": str(min(prices)),
                "yes_close_dollars": str(prices[-1]),
                "yes_vwap_dollars": vwap,
            }
        else:
            price_values = {
                "yes_open_dollars": "",
                "yes_high_dollars": "",
                "yes_low_dollars": "",
                "yes_close_dollars": "",
                "yes_vwap_dollars": "",
            }
        second_writer.writerow(
            {
                "second_utc": datetime.fromtimestamp(
                    stamp, timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                "ticker": market["ticker"],
                "seconds_to_close": close_second - stamp,
                "last_yes_price_dollars": last_price,
                **price_values,
                "trade_count": len(ticks),
                "contracts_fp": str(total),
                "taker_yes_contracts_fp": str(yes_total),
                "taker_no_contracts_fp": str(no_total),
                "market_result": result,
            }
        )
        second_rows += 1
    return len(trades), second_rows


def open_daily_writers(output: Path, dates: list[date], suffix: str, fields: tuple):
    handles, writers, paths = {}, {}, {}
    for day in dates:
        final_path = output / f"{SERIES}-{suffix}-{day.isoformat()}.csv.gz"
        partial_path = final_path.with_suffix(final_path.suffix + ".part")
        handle = gzip.open(partial_path, "wt", newline="", compresslevel=6)
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        handles[day], writers[day], paths[day] = handle, writer, (
            partial_path,
            final_path,
        )
    return handles, writers, paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 7, 27))
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=date(2026, 7, 30),
        help="exclusive UTC end date",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "kalshi_ticks",
    )
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("--end must be after --start")

    start = datetime.combine(args.start, datetime.min.time(), timezone.utc)
    end = datetime.combine(args.end, datetime.min.time(), timezone.utc)
    dates = [
        args.start + timedelta(days=offset)
        for offset in range((args.end - args.start).days)
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    markets = fetch_markets(start, end)
    print(f"Found {len(markets)} {SERIES} markets")

    raw_handles, raw_writers, raw_paths = open_daily_writers(
        args.output, dates, "trades", RAW_FIELDS
    )
    second_handles, second_writers, second_paths = open_daily_writers(
        args.output, dates, "1s", SECOND_FIELDS
    )
    total_trades = total_seconds = completed = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            market_iter = iter(markets)
            pending = {}
            for _ in range(args.workers * 3):
                market = next(market_iter, None)
                if market is None:
                    break
                pending[pool.submit(fetch_trades, market["ticker"])] = market
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    market = pending.pop(future)
                    trades = future.result()
                    day = parse_time(market["close_time"]).date()
                    if day not in raw_writers:
                        raise RuntimeError(f"unexpected market date {day}")
                    trade_count, second_count = write_market(
                        raw_writers[day], second_writers[day], market, trades
                    )
                    total_trades += trade_count
                    total_seconds += second_count
                    completed += 1
                    if completed % 10 == 0 or completed == len(markets):
                        print(
                            f"{completed}/{len(markets)} markets, "
                            f"{total_trades} trades"
                        )
                    next_market = next(market_iter, None)
                    if next_market is not None:
                        pending[
                            pool.submit(fetch_trades, next_market["ticker"])
                        ] = next_market
    finally:
        for handle in [*raw_handles.values(), *second_handles.values()]:
            handle.close()

    for paths in (raw_paths, second_paths):
        for partial_path, final_path in paths.values():
            partial_path.replace(final_path)

    market_path = args.output / f"{SERIES}-markets-{args.start}_{args.end}.csv.gz"
    with gzip.open(market_path, "wt", newline="", compresslevel=6) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=MARKET_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(markets)

    data_files = sorted(args.output.glob("*.csv.gz"))
    manifest = {
        "source": "Kalshi public Trade API",
        "base_url": BASE_URL,
        "series": SERIES,
        "start_utc_inclusive": start.isoformat(),
        "end_utc_exclusive": end.isoformat(),
        "market_count": len(markets),
        "raw_trade_count": total_trades,
        "dense_second_rows": total_seconds,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in data_files
        ],
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Wrote {len(data_files)} data files: {total_trades} raw trades and "
        f"{total_seconds} second rows"
    )


if __name__ == "__main__":
    main()

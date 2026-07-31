#!/usr/bin/env python3
"""Capture the live KXBTC15M market, its full public book, and executions."""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def request_json(path: str, params: dict[str, object] | None = None) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"{BASE_URL}{path}{query}",
        headers={"User-Agent": "btpred-kalshi-15m-recorder/1.0"},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 4:
                raise
            retry_after = float(error.headers.get("Retry-After", "1"))
            time.sleep(max(retry_after, min(10, 0.5 * 2**attempt)))
    raise AssertionError("unreachable")


def parse_time(value: str) -> float:
    pattern = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc).timestamp()


def current_markets() -> list[dict]:
    page = request_json("/markets", {"series_ticker": SERIES, "status": "open", "limit": 100})
    return page.get("markets", [])


def fetch_trades(ticker: str, min_ts: int) -> list[dict]:
    rows: list[dict] = []
    cursor = ""
    while True:
        params: dict[str, object] = {"ticker": ticker, "min_ts": min_ts, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        page = request_json("/markets/trades", params)
        rows.extend(page.get("trades", []))
        cursor = page.get("cursor", "")
        if not cursor:
            return sorted(rows, key=lambda row: (row["created_time"], row["trade_id"]))


def write_record(sink: gzip.GzipFile, record: dict) -> None:
    sink.write((json.dumps(record, separators=(",", ":")) + "\n").encode())


def capture(
    output: Path, seconds: int, poll_ms: int, depth: int, trade_poll_seconds: float
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + seconds if seconds else None
    seen_ids: set[str] = set()
    recent_ids: deque[str] = deque()
    watermarks: dict[str, int] = {}
    next_trade_poll: dict[str, float] = {}
    market_details: dict[str, dict] = {}
    next_poll = time.monotonic()

    with gzip.open(output, "ab") as sink, concurrent.futures.ThreadPoolExecutor(
        max_workers=12
    ) as pool:
        while deadline is None or time.monotonic() < deadline:
            next_poll += poll_ms / 1000
            received_ns = time.time_ns()
            try:
                markets = current_markets()
                if not markets:
                    raise RuntimeError(f"no open {SERIES} market returned")
                futures: list[tuple[str, concurrent.futures.Future]] = []
                for market in markets:
                    ticker = market["ticker"]
                    watermarks.setdefault(ticker, int(time.time()) - 5)
                    futures.append(
                        (
                            f"book:{ticker}",
                            pool.submit(
                                request_json,
                                f"/markets/{ticker}/orderbook",
                                {"depth": depth},
                            ),
                        )
                    )
                    if ticker not in market_details:
                        futures.append(
                            (f"detail:{ticker}", pool.submit(request_json, f"/markets/{ticker}"))
                        )
                    if time.monotonic() >= next_trade_poll.get(ticker, 0):
                        futures.append(
                            (f"trades:{ticker}", pool.submit(fetch_trades, ticker, watermarks[ticker]))
                        )
                        next_trade_poll[ticker] = time.monotonic() + trade_poll_seconds
                values = {name: future.result() for name, future in futures}
                for listed_market in markets:
                    ticker = listed_market["ticker"]
                    if f"detail:{ticker}" in values:
                        market_details[ticker] = values[f"detail:{ticker}"]["market"]
                    market = {**market_details.get(ticker, {}), **listed_market}
                    write_record(
                        sink,
                        {
                            "schema_version": 1,
                            "type": "snapshot",
                            "received_ns": received_ns,
                            "series_ticker": SERIES,
                            "ticker": ticker,
                            "market": market,
                            "orderbook": values[f"book:{ticker}"].get("orderbook_fp"),
                        },
                    )
                    newest = watermarks[ticker]
                    for trade in values.get(f"trades:{ticker}", []):
                        newest = max(newest, int(parse_time(trade["created_time"])))
                        trade_id = trade["trade_id"]
                        if trade_id in seen_ids:
                            continue
                        write_record(
                            sink,
                            {
                                "schema_version": 1,
                                "type": "trade",
                                "received_ns": time.time_ns(),
                                "series_ticker": SERIES,
                                **trade,
                            },
                        )
                        seen_ids.add(trade_id)
                        recent_ids.append(trade_id)
                        if len(recent_ids) > 200_000:
                            seen_ids.remove(recent_ids.popleft())
                    watermarks[ticker] = max(watermarks[ticker], newest - 1)
                sink.flush()
            except Exception as error:
                write_record(
                    sink,
                    {
                        "schema_version": 1,
                        "type": "error",
                        "received_ns": time.time_ns(),
                        "series_ticker": SERIES,
                        "error": f"{type(error).__name__}: {error}",
                    },
                )
                sink.flush()

            delay = next_poll - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_poll = time.monotonic()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=3600, help="duration; 0 runs until interrupted")
    parser.add_argument("--poll-ms", type=int, default=1000)
    parser.add_argument("--depth", type=int, default=100)
    parser.add_argument(
        "--trade-poll-seconds",
        type=float,
        default=5.0,
        help="trade REST poll interval; returned trades retain subsecond timestamps",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.poll_ms < 200 or args.trade_poll_seconds <= 0:
        parser.error("--poll-ms must be at least 200 and --trade-poll-seconds positive")
    output = args.output or Path("runtime/kalshi_15m") / f"{SERIES}-{utc_stamp()}.jsonl.gz"
    capture(output, args.seconds, args.poll_ms, args.depth, args.trade_poll_seconds)
    print(output)


if __name__ == "__main__":
    main()

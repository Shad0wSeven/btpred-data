#!/usr/bin/env python3
"""Capture Kalshi BTC perpetual reference prices, book snapshots, and trades."""

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
from decimal import Decimal
from pathlib import Path

BASE_URL = "https://external-api.kalshi.com/trade-api/v2/margin"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def request_json(path: str, params: dict[str, object] | None = None) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"{BASE_URL}{path}{query}",
        headers={"User-Agent": "btpred-kalshi-perp-recorder/1.0"},
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


def scaled_price(value: str | None, contract_size: Decimal) -> str | None:
    if value is None or contract_size == 0:
        return None
    return format(Decimal(value) / contract_size, "f")


def enrich_market(market: dict) -> dict:
    contract_size = Decimal(market["contract_size"])
    reference = market.get("reference_price") or {}
    settlement = market.get("settlement_mark_price") or {}
    liquidation = market.get("liquidation_mark_price") or {}
    bid = market.get("bid")
    ask = market.get("ask")
    midpoint = (
        (Decimal(bid) + Decimal(ask)) / 2 if bid is not None and ask is not None else None
    )
    reference_value = Decimal(reference["price"]) if reference.get("price") else None
    settlement_value = Decimal(settlement["price"]) if settlement.get("price") else None
    premium_bps = None
    if reference_value and settlement_value:
        premium_bps = format(
            (settlement_value / reference_value - Decimal(1)) * Decimal(10_000),
            "f",
        )
    return {
        "brti_usd": scaled_price(reference.get("price"), contract_size),
        "reference_ts_ms": reference.get("ts_ms"),
        "perp_mid_usd": scaled_price(
            format(midpoint, "f") if midpoint is not None else None, contract_size
        ),
        "settlement_mark_usd": scaled_price(settlement.get("price"), contract_size),
        "liquidation_mark_usd": scaled_price(liquidation.get("price"), contract_size),
        "settlement_premium_bps": premium_bps,
    }


def fetch_trades(ticker: str, min_ts: int) -> list[dict]:
    trades: list[dict] = []
    cursor = ""
    while True:
        params: dict[str, object] = {
            "ticker": ticker,
            "limit": 1000,
            "min_ts": min_ts,
        }
        if cursor:
            params["cursor"] = cursor
        page = request_json("/trades", params)
        trades.extend(page.get("trades", []))
        cursor = page.get("cursor", "")
        if not cursor:
            break
    return sorted(trades, key=lambda row: (row["created_time"], row["trade_id"]))


def write_record(sink: gzip.GzipFile, record: dict) -> None:
    sink.write((json.dumps(record, separators=(",", ":")) + "\n").encode())


def capture(ticker: str, output: Path, seconds: int, poll_ms: int, depth: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + seconds if seconds else None
    recent_ids: deque[str] = deque()
    recent_set: set[str] = set()
    trade_watermark = int(time.time()) - 5
    next_poll = time.monotonic()

    with gzip.open(output, "ab") as sink, concurrent.futures.ThreadPoolExecutor(
        max_workers=3
    ) as pool:
        while deadline is None or time.monotonic() < deadline:
            next_poll += poll_ms / 1000
            received_ns = time.time_ns()
            try:
                market_future = pool.submit(request_json, f"/markets/{ticker}")
                book_future = pool.submit(
                    request_json, f"/markets/{ticker}/orderbook", {"depth": depth}
                )
                trades_future = pool.submit(fetch_trades, ticker, trade_watermark)
                market = market_future.result()["market"]
                orderbook = book_future.result()["orderbook"]
                trades = trades_future.result()

                write_record(
                    sink,
                    {
                        "schema_version": 1,
                        "type": "snapshot",
                        "received_ns": received_ns,
                        "ticker": ticker,
                        "derived": enrich_market(market),
                        "market": market,
                        "orderbook": orderbook,
                    },
                )
                newest_trade = trade_watermark
                for trade in trades:
                    newest_trade = max(newest_trade, int(parse_time(trade["created_time"])))
                    trade_id = trade["trade_id"]
                    if trade_id in recent_set:
                        continue
                    contract_size = Decimal(market["contract_size"])
                    write_record(
                        sink,
                        {
                            "schema_version": 1,
                            "type": "trade",
                            "received_ns": time.time_ns(),
                            "underlying_price_usd": scaled_price(
                                trade["price"], contract_size
                            ),
                            **trade,
                        },
                    )
                    recent_ids.append(trade_id)
                    recent_set.add(trade_id)
                    if len(recent_ids) > 100_000:
                        recent_set.remove(recent_ids.popleft())
                trade_watermark = max(trade_watermark, newest_trade - 1)
                sink.flush()
            except Exception as error:  # retain diagnostics and keep the recorder alive
                write_record(
                    sink,
                    {
                        "schema_version": 1,
                        "type": "error",
                        "received_ns": time.time_ns(),
                        "ticker": ticker,
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
    parser.add_argument("--ticker", default="KXBTCPERP")
    parser.add_argument(
        "--seconds", type=int, default=3600, help="duration; 0 runs until interrupted"
    )
    parser.add_argument(
        "--poll-ms",
        type=int,
        default=1000,
        help="REST snapshot interval; BRTI reference_price updates once per second",
    )
    parser.add_argument("--depth", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.poll_ms < 200:
        parser.error("--poll-ms must be at least 200")
    output = args.output or Path("runtime/kalshi_perp") / (
        f"{args.ticker}-market-{utc_stamp()}.jsonl.gz"
    )
    capture(args.ticker, output, args.seconds, args.poll_ms, args.depth)
    print(output)


if __name__ == "__main__":
    main()

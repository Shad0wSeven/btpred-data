#!/usr/bin/env python3
"""Capture a synchronized Binance spot L2 snapshot and 100 ms diff stream."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import websockets

REST_URL = "https://data-api.binance.vision/api/v3/depth"
STREAM_URL = "wss://data-stream.binance.vision/ws"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fetch_snapshot(symbol: str) -> dict:
    query = urllib.parse.urlencode({"symbol": symbol.upper(), "limit": 5000})
    request = urllib.request.Request(
        f"{REST_URL}?{query}", headers={"User-Agent": "btpred-l2-recorder/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def apply_updates(book: dict[str, Decimal], updates: list[list[str]]) -> None:
    for price, quantity in updates:
        if Decimal(quantity) == 0:
            book.pop(price, None)
        else:
            book[price] = Decimal(quantity)


def write_record(sink: gzip.GzipFile, record: dict) -> None:
    sink.write((json.dumps(record, separators=(",", ":")) + "\n").encode())


async def capture(symbol: str, output: Path, seconds: int) -> None:
    stream = f"{STREAM_URL}/{symbol.lower()}@depth@100ms"
    deadline = time.monotonic() + seconds if seconds else None
    output.parent.mkdir(parents=True, exist_ok=True)

    while deadline is None or time.monotonic() < deadline:
        try:
            async with websockets.connect(
                stream, ping_interval=20, ping_timeout=20, max_queue=100_000
            ) as websocket:
                snapshot = await asyncio.to_thread(fetch_snapshot, symbol)
                bids = {price: Decimal(qty) for price, qty in snapshot["bids"]}
                asks = {price: Decimal(qty) for price, qty in snapshot["asks"]}
                last_update_id = snapshot["lastUpdateId"]

                with gzip.open(output, "ab") as sink:
                    write_record(
                        sink,
                        {
                            "type": "snapshot",
                            "received_ns": time.time_ns(),
                            "symbol": symbol.upper(),
                            **snapshot,
                        },
                    )
                    synchronized = False
                    async for raw in websocket:
                        event = json.loads(raw)
                        received_ns = time.time_ns()
                        if event["u"] <= last_update_id:
                            continue
                        if not synchronized:
                            if event["U"] > last_update_id + 1:
                                raise RuntimeError("snapshot/stream gap; resynchronizing")
                            synchronized = event["U"] <= last_update_id + 1 <= event["u"]
                            if not synchronized:
                                continue
                        elif event["U"] > last_update_id + 1:
                            raise RuntimeError("diff-stream sequence gap; resynchronizing")

                        apply_updates(bids, event["b"])
                        apply_updates(asks, event["a"])
                        last_update_id = event["u"]
                        write_record(
                            sink,
                            {
                                "type": "depthUpdate",
                                "received_ns": received_ns,
                                **event,
                            },
                        )
                        if deadline is not None and time.monotonic() >= deadline:
                            return
        except (OSError, TimeoutError, websockets.WebSocketException, RuntimeError) as error:
            print(f"{error}; reconnecting with a fresh snapshot")
            await asyncio.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCFDUSD")
    parser.add_argument(
        "--seconds",
        type=int,
        default=900,
        help="capture duration; use 0 to run until interrupted",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path("l2_capture") / (
        f"{args.symbol.upper()}-depth-{utc_stamp()}.jsonl.gz"
    )
    asyncio.run(capture(args.symbol, output, args.seconds))
    print(output)


if __name__ == "__main__":
    main()

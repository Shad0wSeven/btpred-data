#!/usr/bin/env python3
"""Create a causal subsecond BRTI estimate from Kalshi BTC perp event data.

The official BRTI `reference_price` is a one-second anchor. Between anchors,
the estimator uses the perp microprice/trade tape minus an exponentially
smoothed perp-to-BRTI basis. Output rows are estimates, never official BRTI.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def parse_time_ns(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1e9)


def ema_alpha(delta_seconds: float, half_life_seconds: float) -> float:
    return 1 - math.exp(-math.log(2) * max(delta_seconds, 0) / half_life_seconds)


def microprice(market: dict, orderbook: dict | None) -> Decimal | None:
    if not orderbook:
        return None
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])
    if not bids or not asks:
        return None
    bid_price, bid_size = max(bids, key=lambda level: Decimal(level[0]))
    ask_price, ask_size = min(asks, key=lambda level: Decimal(level[0]))
    bid_size_decimal = Decimal(bid_size)
    ask_size_decimal = Decimal(ask_size)
    if bid_size_decimal + ask_size_decimal == 0:
        return None
    return (
        Decimal(ask_price) * bid_size_decimal + Decimal(bid_price) * ask_size_decimal
    ) / (bid_size_decimal + ask_size_decimal)


def read_events(path: Path) -> list[dict]:
    events: list[dict] = []
    seen_trades: set[str] = set()
    with gzip.open(path, "rt") as source:
        for line in source:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") == "snapshot":
                events.append({"time_ns": int(record["received_ns"]), "record": record})
            elif record.get("type") == "trade" and record["trade_id"] not in seen_trades:
                seen_trades.add(record["trade_id"])
                events.append({"time_ns": parse_time_ns(record["created_time"]), "record": record})
    return sorted(events, key=lambda event: event["time_ns"])


def estimate(
    input_path: Path,
    output_path: Path,
    price_half_life: float,
    basis_half_life: float,
) -> int:
    events = read_events(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    contract_size: Decimal | None = None
    perp_ema: Decimal | None = None
    basis_ema: Decimal | None = None
    basis_abs_error_ema = Decimal(0)
    last_time_ns: int | None = None
    rows = 0

    with gzip.open(output_path, "wt", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=[
                "event_time_utc",
                "event_time_ns",
                "source",
                "inferred_brti_usd",
                "official_brti_anchor_usd",
                "perp_observation_usd",
                "perp_ema_usd",
                "basis_ema_perp_usd",
                "basis_error_ema_usd",
            ],
        )
        writer.writeheader()
        for event in events:
            record = event["record"]
            event_ns = event["time_ns"]
            delta_seconds = 0 if last_time_ns is None else (event_ns - last_time_ns) / 1e9
            last_time_ns = event_ns
            source = record["type"]
            official_anchor: Decimal | None = None

            if source == "snapshot":
                market = record["market"]
                contract_size = Decimal(market["contract_size"])
                observation = microprice(market, record.get("orderbook"))
                reference = market.get("reference_price") or {}
                if reference.get("price") is not None:
                    official_anchor = Decimal(reference["price"]) / contract_size
            else:
                if contract_size is None:
                    continue
                observation = Decimal(record["price"])

            if observation is None or contract_size is None:
                continue
            if perp_ema is None:
                perp_ema = observation
            else:
                alpha_price = Decimal(str(ema_alpha(delta_seconds, price_half_life)))
                perp_ema += alpha_price * (observation - perp_ema)

            if official_anchor is not None:
                observed_basis = perp_ema - official_anchor * contract_size
                if basis_ema is None:
                    basis_ema = observed_basis
                else:
                    alpha_basis = Decimal(str(ema_alpha(delta_seconds, basis_half_life)))
                    residual = observed_basis - basis_ema
                    basis_abs_error_ema += alpha_basis * (abs(residual) - basis_abs_error_ema)
                    basis_ema += alpha_basis * residual

            if basis_ema is None:
                continue
            inferred = official_anchor or ((perp_ema - basis_ema) / contract_size)
            stamp = datetime.fromtimestamp(event_ns / 1e9, timezone.utc).isoformat()
            writer.writerow(
                {
                    "event_time_utc": stamp,
                    "event_time_ns": event_ns,
                    "source": source,
                    "inferred_brti_usd": format(inferred, "f"),
                    "official_brti_anchor_usd": format(official_anchor, "f") if official_anchor else "",
                    "perp_observation_usd": format(observation / contract_size, "f"),
                    "perp_ema_usd": format(perp_ema / contract_size, "f"),
                    "basis_ema_perp_usd": format(basis_ema / contract_size, "f"),
                    "basis_error_ema_usd": format(basis_abs_error_ema / contract_size, "f"),
                }
            )
            rows += 1
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="KXBTCPERP capture .jsonl.gz")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--price-half-life", type=float, default=0.25)
    parser.add_argument("--basis-half-life", type=float, default=30.0)
    args = parser.parse_args()
    if args.price_half_life <= 0 or args.basis_half_life <= 0:
        parser.error("EMA half-lives must be positive")
    output = args.output or args.input.with_name(args.input.stem.replace(".jsonl", "") + "-brti-estimates.csv.gz")
    rows = estimate(args.input, output, args.price_half_life, args.basis_half_life)
    print(f"{output} ({rows} event-time estimates)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create hourly BTCFDUSD bars and run simple next-hour price forecasts.

All model inputs at time t are known by the close of hour t; each forecast is
for the close of hour t+1.  This intentionally avoids look-ahead bias.
"""
import csv
import glob
import math
import os
import zipfile
from datetime import datetime, timezone

import numpy as np


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPOT_FILES = sorted(glob.glob(os.path.join(ROOT, "spot", "BTCFDUSD-1m-*.zip")))
OUT_BARS = os.path.join(os.path.dirname(__file__), "hourly_bars.csv")
OUT_FORECASTS = os.path.join(os.path.dirname(__file__), "hourly_forecasts.csv")
OUT_REPORT = os.path.join(os.path.dirname(__file__), "backtest_report.md")


def load_hourly_bars():
    bars = {}
    for path in SPOT_FILES:
        with zipfile.ZipFile(path) as archive:
            member = archive.namelist()[0]
            with archive.open(member) as raw:
                for row in csv.reader((line.decode("utf-8") for line in raw)):
                    # Binance spot archives switched to microsecond timestamps in 2025.
                    # Normalize both archive formats to milliseconds before bucketing.
                    open_time = int(row[0])
                    if open_time > 100_000_000_000_000:
                        open_time //= 1_000
                    hour = (open_time // 3_600_000) * 3_600_000
                    price_open, high, low, close = map(float, row[1:5])
                    volume, quote_volume = map(float, (row[5], row[7]))
                    trades, buy_quote = int(row[8]), float(row[10])
                    if hour not in bars:
                        bars[hour] = [price_open, high, low, close, volume, quote_volume, trades, buy_quote]
                    else:
                        bar = bars[hour]
                        bar[1] = max(bar[1], high)
                        bar[2] = min(bar[2], low)
                        bar[3] = close
                        bar[4] += volume
                        bar[5] += quote_volume
                        bar[6] += trades
                        bar[7] += buy_quote
    return [(stamp, *bars[stamp]) for stamp in sorted(bars)]


def rolling_mean(values, end, width):
    start = max(0, end - width + 1)
    return float(np.mean(values[start:end + 1]))


def main():
    bars = load_hourly_bars()
    stamps = np.array([b[0] for b in bars], dtype=np.int64)
    o = np.array([b[1] for b in bars])
    h = np.array([b[2] for b in bars])
    l = np.array([b[3] for b in bars])
    c = np.array([b[4] for b in bars])
    base_vol = np.array([b[5] for b in bars])
    quote_vol = np.array([b[6] for b in bars])
    trades = np.array([b[7] for b in bars])
    buy_quote = np.array([b[8] for b in bars])
    ret = np.zeros(len(c))
    ret[1:] = np.log(c[1:] / c[:-1])
    hourly_range = (h - l) / c
    buy_ratio = np.divide(buy_quote, quote_vol, out=np.full(len(c), 0.5), where=quote_vol > 0)

    # i forecasts the close at i+1. Start after enough history for all signals.
    rows, features, targets = [], [], []
    for i in range(48, len(c) - 1):
        vol24 = float(np.std(ret[i - 23:i + 1], ddof=1))
        mean_vol24 = rolling_mean(quote_vol, i - 1, 24)
        volume_z = (quote_vol[i] / mean_vol24 - 1.0) if mean_vol24 else 0.0
        momentum6 = float(np.sum(ret[i - 5:i + 1]))
        momentum24 = float(np.sum(ret[i - 23:i + 1]))
        feature = [ret[i], momentum6, momentum24, vol24, volume_z, hourly_range[i], buy_ratio[i] - 0.5]
        rows.append((i, vol24, volume_z, momentum6, momentum24, buy_ratio[i]))
        features.append(feature)
        targets.append(ret[i + 1])
    x, y = np.array(features), np.array(targets)

    # Final 30 days are the holdout. Ridge keeps a small, noisy data set stable.
    split_stamp = stamps[-1] - 30 * 24 * 3_600_000
    test_mask = np.array([stamps[rows[k][0] + 1] >= split_stamp for k in range(len(rows))])
    train_mask = ~test_mask
    mu, sigma = x[train_mask].mean(axis=0), x[train_mask].std(axis=0)
    sigma[sigma == 0] = 1.0
    xz = (x - mu) / sigma
    design = np.column_stack((np.ones(train_mask.sum()), xz[train_mask]))
    ridge = np.eye(design.shape[1]) * 10.0
    ridge[0, 0] = 0.0
    coef = np.linalg.solve(design.T @ design + ridge, design.T @ y[train_mask])
    linear_return = np.column_stack((np.ones(len(x)), xz)) @ coef

    preds = {"last_close": [], "same_hour_yesterday": [], "sma_24": [], "momentum_24": [], "signal_ridge": []}
    actual = []
    output_rows = []
    for k, (i, vol24, volume_z, mom6, mom24, buy) in enumerate(rows):
        next_close = c[i + 1]
        values = {
            "last_close": c[i],
            "same_hour_yesterday": c[i - 23],
            "sma_24": float(np.mean(c[i - 23:i + 1])),
            "momentum_24": c[i] * math.exp(mom24 / 24),
            "signal_ridge": c[i] * math.exp(float(np.clip(linear_return[k], -0.05, 0.05))),
        }
        actual.append(next_close)
        for name in preds:
            preds[name].append(values[name])
        stamp = datetime.fromtimestamp(stamps[i + 1] / 1000, tz=timezone.utc).isoformat()
        output_rows.append([stamp, next_close, vol24, volume_z, mom6, mom24, buy, *[values[n] for n in preds]])

    with open(OUT_BARS, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["open_time_utc", "open", "high", "low", "close", "base_volume", "quote_volume", "trades", "taker_buy_quote_volume"])
        for b in bars:
            writer.writerow([datetime.fromtimestamp(b[0] / 1000, tz=timezone.utc).isoformat(), *b[1:]])
    with open(OUT_FORECASTS, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["target_hour_utc", "actual_close", "trailing_24h_return_volatility", "volume_vs_prior_24h", "momentum_6h", "momentum_24h", "taker_buy_ratio", *preds.keys()])
        writer.writerows(output_rows)

    actual, test_mask = np.array(actual), test_mask
    report = ["# Hourly BTCFDUSD naive forecast backtest", "", f"Source: {len(SPOT_FILES)} monthly Binance 1-minute archives, aggregated to {len(bars)} UTC hourly bars.", "", "Forecast target: next hour's close. Holdout: final 30 days. All signals are lagged to the forecast origin.", "", "| Model | Holdout MAE (USD) | Holdout RMSE (USD) | Direction accuracy |", "|---|---:|---:|---:|"]
    for name, values in preds.items():
        values = np.array(values)
        err = values[test_mask] - actual[test_mask]
        predicted_move = np.sign(values[test_mask] - c[np.array([r[0] for r in rows])[test_mask]])
        actual_move = np.sign(actual[test_mask] - c[np.array([r[0] for r in rows])[test_mask]])
        nonzero = predicted_move != 0
        direction_text = f"{np.mean(predicted_move[nonzero] == actual_move[nonzero]):.1%}" if np.any(nonzero) else "n/a"
        report.append(f"| {name} | {np.mean(np.abs(err)):.2f} | {np.sqrt(np.mean(err**2)):.2f} | {direction_text} |")
    report.extend(["", "Signals in `signal_ridge`: current 1h return, 6h/24h momentum, trailing 24h return volatility, quote-volume surprise vs. the preceding 24h, hourly high-low range, and taker-buy quote-volume ratio. This is a baseline comparison, not an investable strategy."])
    with open(OUT_REPORT, "w") as handle:
        handle.write("\n".join(report) + "\n")


if __name__ == "__main__":
    main()

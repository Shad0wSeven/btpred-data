#!/usr/bin/env python3
"""Test whether Binance aggregate-trade flow improves 15m up/down pricing."""
import csv
import glob
import math
import os
import zipfile
from datetime import datetime, timezone

import numpy as np

import kalshi_15m_pricer as base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))


def tick_minutes(stamps):
    """Minute-level signed aggressive notional and arrival features from aggTrades.

    Binance's isBuyerMaker=True means the aggressive side is selling, so signed
    notional is negative; False means aggressive buying and is positive.
    """
    index = {int(t): i for i, t in enumerate(stamps)}
    signed = np.zeros(len(stamps)); total = np.zeros(len(stamps))
    aggs = np.zeros(len(stamps)); underlying_trades = np.zeros(len(stamps)); signed_count = np.zeros(len(stamps))
    paths = sorted(glob.glob(os.path.join(ROOT, "ticks", "*.zip")))
    for path in paths:
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as raw:
            for row in csv.reader(line.decode("utf-8") for line in raw):
                ts = int(row[5]); ts = ts // 1000 if ts > 100_000_000_000_000 else ts
                i = index.get((ts // 60_000) * 60_000)
                if i is None:
                    continue
                value = float(row[1]) * float(row[2])
                direction = -1.0 if row[6].lower() == "true" else 1.0
                signed[i] += direction * value; total[i] += value; aggs[i] += 1
                underlying_trades[i] += int(row[4]) - int(row[3]) + 1
                signed_count[i] += direction
    return signed, total, aggs, underlying_trades, signed_count


def tick_features(origins, signed, total, aggs, trades, signed_count):
    ps, pt, pa, pn, pc = (np.r_[0., np.cumsum(x)] for x in (signed, total, aggs, trades, signed_count))
    columns, names = [], []
    for w in (1, 5, 15, 30, 60, 120):
        start = origins - w + 1
        flow, amount = ps[origins + 1] - ps[start], pt[origins + 1] - pt[start]
        arrivals, ntrades, signed_n = pa[origins + 1] - pa[start], pn[origins + 1] - pn[start], pc[origins + 1] - pc[start]
        columns += [np.divide(flow, amount, out=np.zeros(len(origins)), where=amount > 0), np.log1p(arrivals / w), np.divide(signed_n, arrivals, out=np.zeros(len(origins)), where=arrivals > 0), np.log1p(ntrades / w)]
        names += [f"tick_flow_imbalance_{w}m", f"tick_agg_arrival_{w}m", f"tick_signed_count_{w}m", f"tick_trade_intensity_{w}m"]
    return np.column_stack(columns), names


def main():
    bars = base.load_bars()
    stamps = np.array([x[0] for x in bars], dtype=np.int64)
    high, low, close, volume, buy = (np.array([x[i] for x in bars]) for i in range(1, 6))
    origins = np.arange(120, len(close) - 15)
    bar_x, _ = base.make_features(high, low, close, volume, buy, origins)
    bar_names = list(base.FEATURE_NAMES)
    signed, total, aggs, trades, signed_count = tick_minutes(stamps)
    tick_x, tick_names = tick_features(origins, signed, total, aggs, trades, signed_count)
    x_raw = np.column_stack((bar_x, tick_x)); names = bar_names + tick_names
    ret = np.log(close[origins + 15] / close[origins]) * 10_000
    y = (ret > 0).astype(float)
    n = len(origins); a, b = int(.70*n), int(.80*n)
    train, val, test = np.arange(a), np.arange(a,b), np.arange(b,n)
    mean, sd = x_raw[train].mean(0), x_raw[train].std(0); sd[sd < 1e-8] = 1
    x = (x_raw - mean) / sd
    candidates = (.001, .003, .01, .03, .1, .3)
    models = [(v, base.fit_logit(x[train], y[train], v)) for v in candidates]
    l2, model = min(models, key=lambda item: base.logloss(base.predict(item[1], x[val]), y[val]))
    val_raw = base.predict(model, x[val])
    calibrator = base.fit_logit(np.log(val_raw/(1-val_raw))[:,None], y[val], .03)
    def calibrated(p):
        p = np.clip(p, 1e-5, 1-1e-5)
        return base.predict(calibrator, np.log(p/(1-p))[:,None])
    pred = calibrated(base.predict(model, x[test]))
    # Exactly the same holdout protocol as the bar-only study.
    nonoverlap = np.arange(0, len(test), 15)
    p, yt = pred[nonoverlap], y[test][nonoverlap]
    # Bar-only score from stored earlier study; tested here only as a reference.
    prior = np.full(len(p), y[train].mean())
    ranking = sorted(zip(names, model[1:] / sd), key=lambda q: abs(q[1]), reverse=True)
    vol_col = bar_names.index("realized_vol_30m_bps")
    cutoffs = np.quantile(bar_x[train, vol_col], (1/3, 2/3))
    regimes = np.digitize(bar_x[:, vol_col], cutoffs)
    regime_rows = []
    for bucket in range(3):
        take = regimes[test][nonoverlap] == bucket
        if take.sum():
            regime_rows.append((bucket, int(take.sum()), base.logloss(p[take], yt[take]), base.brier(p[take], yt[take]), float(yt[take].mean())))
    report = ["# Tick-level incremental test: 15-minute BTC up/down", "", "Aggregate-trade inputs: signed aggressive notional, aggregate-trade arrival rate, signed trade-count imbalance, and underlying trade intensity across 1, 5, 15, 30, 60, and 120-minute windows. All are computed strictly before the contract origin.", "", "## Untouched final-20% walk-forward result", "", "| Model | Log loss | Brier score |", "|---|---:|---:|", f"| Constant prior | {base.logloss(prior, yt):.4f} | {base.brier(prior, yt):.4f} |", "| Bar-only selected model (prior run) | 0.6938 | 0.2503 |", f"| Bar + aggregate-trade tick model | {base.logloss(p, yt):.4f} | {base.brier(p, yt):.4f} |", "", f"Selected L2: {l2}. Test contracts: {len(yt)} non-overlapping 15-minute settlements.", "", "## Strongest fitted features", ""]
    for name, coefficient in ranking[:15]: report.append(f"- {name}: {coefficient:+.5f}")
    report += ["", "## Final-test volatility-regime breakdown", "", "| Regime (30m realized vol) | Contracts | Tick log loss | Tick Brier | Realized up frequency |", "|---|---:|---:|---:|---:|"]
    for bucket, count, ll, br, frequency in regime_rows:
        report.append(f"| {('low', 'medium', 'high')[bucket]} | {count} | {ll:.4f} | {br:.4f} | {frequency:.1%} |")
    report += ["", "Interpretation: only claim a tick upgrade if it improves both log loss and Brier versus the bar-only model on this untouched test. Otherwise its value is data plumbing for the next iteration, not trading evidence."]
    with open(os.path.join(HERE, "tick_upgrade_report.md"), "w") as h: h.write("\n".join(report) + "\n")
    with open(os.path.join(HERE, "tick_midpoint_backtest.csv"), "w", newline="") as h:
        w = csv.writer(h); w.writerow(["origin_utc", "actual_up", "actual_return_bps", "tick_up_probability", "tick_mid_cents"])
        for j in nonoverlap:
            i = test[j]
            w.writerow([datetime.fromtimestamp(stamps[origins[i]]/1000, timezone.utc).isoformat(), int(y[i]), ret[i], pred[j], pred[j]*100])


if __name__ == "__main__": main()

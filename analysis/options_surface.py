#!/usr/bin/env python3
"""Summarize Binance BTC option IV, smile/skew, and perpetual funding.

The option snapshot already reports mark_iv.  We independently reprice its
mark_price with Black--Scholes (zero rate) as a data-quality diagnostic, then
make a daily surface summary from the 16:00 UTC snapshots.  This is analysis,
not a trading recommendation.
"""
import csv
import glob
import math
import os
import statistics
import zipfile
from collections import defaultdict
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))


def normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot, strike, years, volatility, option_type):
    if years <= 0 or volatility <= 0:
        return max(0.0, spot - strike) if option_type == "C" else max(0.0, strike - spot)
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + 0.5 * volatility * volatility * years) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    if option_type == "C":
        return spot * normal_cdf(d1) - strike * normal_cdf(d2)
    return strike * normal_cdf(-d2) - spot * normal_cdf(-d1)


def archive_rows(pattern):
    for path in sorted(glob.glob(pattern)):
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as raw:
            yield from csv.DictReader(line.decode("utf-8") for line in raw)


def load_hourly_spot():
    closes = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "spot_btcusdt", "*.zip"))):
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as raw:
            for row in csv.reader(line.decode("utf-8") for line in raw):
                stamp = int(row[0])
                if stamp > 100_000_000_000_000:
                    stamp //= 1000
                hour = (stamp // 3_600_000) * 3_600_000
                closes[hour] = float(row[4])
    return closes


def main():
    spot = load_hourly_spot()
    snapshots = defaultdict(list)
    bs_errors = []
    for row in archive_rows(os.path.join(ROOT, "options", "BTCUSDT-EOHSummary-*.zip")):
        if row["hour"] != "16" or not row["mark_iv"]:
            continue
        stamp = int(datetime.strptime(f"{row['date']} {row['hour']}", "%Y-%m-%d %H").replace(tzinfo=timezone.utc).timestamp() * 1000)
        expiry = datetime.strptime(row["symbol"].split("-")[1], "%y%m%d").replace(tzinfo=timezone.utc)
        # Contract symbols contain a date but not time.  08:00 UTC is used as
        # the expiry convention here; this has negligible impact away from expiry.
        expiry = expiry.replace(hour=8)
        years = (expiry.timestamp() * 1000 - stamp) / (365.25 * 24 * 3_600_000)
        if not 1 / 365.25 <= years <= 60 / 365.25:
            continue
        if stamp not in spot:
            continue
        try:
            strike = float(row["strike"].split("-")[1])
            iv, mark, oi, delta = float(row["mark_iv"]), float(row["mark_price"]), float(row["openinterest_usdt"]), float(row["delta"])
        except (ValueError, IndexError):
            continue
        if not (0.01 <= iv <= 4.0 and oi > 0):
            continue
        option = {"strike": strike, "iv": iv, "mark": mark, "oi": oi, "delta": delta, "type": row["type"], "days": years * 365.25, "spot": spot[stamp]}
        if mark > 10:
            theoretical = bs_price(spot[stamp], strike, years, iv, row["type"])
            bs_errors.append(abs(theoretical - mark) / mark)
        snapshots[row["date"]].append(option)

    funding = defaultdict(list)
    for row in archive_rows(os.path.join(ROOT, "perps", "*fundingRate*.zip")):
        day = datetime.fromtimestamp(int(row["calc_time"]) / 1000, timezone.utc).date().isoformat()
        funding[day].append(float(row["last_funding_rate"]))

    summary = []
    for day in sorted(snapshots):
        chain = snapshots[day]
        atm = [x["iv"] for x in chain if abs(math.log(x["strike"] / x["spot"])) <= 0.05 and 7 <= x["days"] <= 45]
        near = [x["iv"] for x in chain if abs(math.log(x["strike"] / x["spot"])) <= 0.05 and 7 <= x["days"] <= 14]
        medium = [x["iv"] for x in chain if abs(math.log(x["strike"] / x["spot"])) <= 0.05 and 21 <= x["days"] <= 45]
        rr = []
        expiries = defaultdict(list)
        for x in chain:
            if 7 <= x["days"] <= 45:
                expiries[round(x["days"], 3)].append(x)
        for expiry_chain in expiries.values():
            calls = [x for x in expiry_chain if x["type"] == "C" and x["delta"] > 0]
            puts = [x for x in expiry_chain if x["type"] == "P" and x["delta"] < 0]
            if calls and puts:
                call25 = min(calls, key=lambda x: abs(x["delta"] - 0.25))
                put25 = min(puts, key=lambda x: abs(x["delta"] + 0.25))
                rr.append(put25["iv"] - call25["iv"])
        stamp = int(datetime.strptime(day, "%Y-%m-%d").replace(hour=16, tzinfo=timezone.utc).timestamp() * 1000)
        # Trailing seven-day realized volatility calculated from 1-hour spot returns.
        series = [spot.get(stamp - offset * 3_600_000) for offset in range(168, -1, -1)]
        series = [x for x in series if x is not None]
        rv = ""
        if len(series) >= 160:
            returns = [math.log(series[i] / series[i - 1]) for i in range(1, len(series))]
            rv = statistics.stdev(returns) * math.sqrt(24 * 365.25)
        summary.append({"date": day, "spot": spot[stamp], "atm_iv": statistics.median(atm) if atm else "", "near_atm_iv": statistics.median(near) if near else "", "medium_atm_iv": statistics.median(medium) if medium else "", "put_minus_call_25d_iv": statistics.median(rr) if rr else "", "trailing_7d_realized_vol": rv, "mean_perp_funding": statistics.mean(funding[day]) if funding[day] else "", "contracts": len(chain)})

    out_csv = os.path.join(HERE, "btc_options_surface_daily.csv")
    fields = list(summary[0])
    with open(out_csv, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)

    valid = [x for x in summary if x["atm_iv"] != "" and x["trailing_7d_realized_vol"] != ""]
    atms = [x["atm_iv"] for x in valid]
    rvs = [x["trailing_7d_realized_vol"] for x in valid]
    corr = statistics.correlation(atms, rvs) if len(valid) > 1 else float("nan")
    changes = []
    for previous, current in zip(valid, valid[1:]):
        if current["atm_iv"] != "" and previous["atm_iv"] != "":
            changes.append((abs(current["atm_iv"] - previous["atm_iv"]), current, current["atm_iv"] - previous["atm_iv"]))
    changes.sort(reverse=True, key=lambda x: x[0])
    report = ["# BTC options: Black--Scholes surface summary", "", "Data: Binance hourly BTC option EOH snapshots (16:00 UTC), matched to Binance BTCUSDT spot and BTCUSDT perpetual funding, 2023-07-01 to 2023-09-30. Options are European and cash-settled.", "", "## What is backed out", "", "The archive exposes `mark_iv`; we use it as the Black--Scholes implied volatility. As a diagnostic, Black--Scholes prices with zero rate, matched spot, the stated IV, and an 08:00 UTC expiry convention are compared with option mark prices. Median absolute relative pricing difference: " + f"{statistics.median(bs_errors):.2%}" + ". Differences include timestamp/settlement-convention mismatch and rounding, so this is a sanity check rather than an arbitrage test.", "", "## Surface behavior", "", f"- Daily 7--45 day ATM IV: median {statistics.median(atms):.1%}; range {min(atms):.1%} to {max(atms):.1%}.", f"- Correlation of ATM IV with trailing 7-day realized volatility: {corr:.2f} ({len(valid)} daily observations).", "- `put_minus_call_25d_iv` is the 25-delta put IV minus 25-delta call IV; positive values indicate relatively dear downside protection.", "- `near_atm_iv` versus `medium_atm_iv` shows the term structure. `mean_perp_funding` gives the average 8-hour perpetual funding rate that day.", "", "## Largest observed ATM-IV changes", "", "| Date | ATM-IV change | ATM IV | Spot |", "|---|---:|---:|---:|"]
    for _, row, change in changes[:5]:
        report.append(f"| {row['date']} | {change:+.1%} | {row['atm_iv']:.1%} | ${row['spot']:,.0f} |")
    report.extend(["", "The daily data set is intentionally descriptive. A proper tradable backtest would require executable bid/ask quotes, fees, contract multipliers, and point-in-time selection rules."])
    with open(os.path.join(HERE, "options_research.md"), "w") as handle:
        handle.write("\n".join(report) + "\n")


if __name__ == "__main__":
    main()

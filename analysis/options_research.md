# BTC options: Black--Scholes surface summary

Data: Binance hourly BTC option EOH snapshots (16:00 UTC), matched to Binance BTCUSDT spot and BTCUSDT perpetual funding, 2023-07-01 to 2023-09-30. Options are European and cash-settled.

## What is backed out

The archive exposes `mark_iv`; we use it as the Black--Scholes implied volatility. As a diagnostic, Black--Scholes prices with zero rate, matched spot, the stated IV, and an 08:00 UTC expiry convention are compared with option mark prices. Median absolute relative pricing difference: 0.26%. Differences include timestamp/settlement-convention mismatch and rounding, so this is a sanity check rather than an arbitrage test.

## Surface behavior

- Daily 7--45 day ATM IV: median 33.7%; range 25.2% to 41.3%.
- Correlation of ATM IV with trailing 7-day realized volatility: 0.44 (73 daily observations).
- `put_minus_call_25d_iv` is the 25-delta put IV minus 25-delta call IV; positive values indicate relatively dear downside protection.
- `near_atm_iv` versus `medium_atm_iv` shows the term structure. `mean_perp_funding` gives the average 8-hour perpetual funding rate that day.

## Largest observed ATM-IV changes

| Date | ATM-IV change | ATM IV | Spot |
|---|---:|---:|---:|
| 2023-08-10 | -5.8% | 30.6% | $29,431 |
| 2023-08-18 | +5.1% | 41.0% | $25,905 |
| 2023-08-12 | -5.1% | 25.2% | $29,457 |
| 2023-09-22 | -4.9% | 29.4% | $26,598 |
| 2023-08-09 | +4.8% | 36.4% | $29,513 |

The daily data set is intentionally descriptive. A proper tradable backtest would require executable bid/ask quotes, fees, contract multipliers, and point-in-time selection rules.

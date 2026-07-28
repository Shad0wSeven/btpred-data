# Tick-level incremental test: 15-minute BTC up/down

Aggregate-trade inputs: signed aggressive notional, aggregate-trade arrival rate, signed trade-count imbalance, and underlying trade intensity across 1, 5, 15, 30, 60, and 120-minute windows. All are computed strictly before the contract origin.

## Untouched final-20% walk-forward result

| Model | Log loss | Brier score |
|---|---:|---:|
| Constant prior | 0.6932 | 0.2500 |
| Bar-only selected model (prior run) | 0.6938 | 0.2503 |
| Bar + aggregate-trade tick model | 0.6937 | 0.2503 |

Selected L2: 0.3. Test contracts: 2245 non-overlapping 15-minute settlements.

## Strongest fitted features

- taker_imbalance_120m: +0.27405
- taker_imbalance_60m: +0.16399
- tick_signed_count_120m: -0.13327
- tick_signed_count_30m: -0.05577
- tick_signed_count_15m: -0.04582
- tick_signed_count_60m: -0.03891
- taker_imbalance_15m: +0.03193
- tick_flow_imbalance_15m: -0.02209
- tick_flow_imbalance_120m: -0.01898
- tick_signed_count_5m: -0.01340
- tick_flow_imbalance_1m: +0.01163
- tick_flow_imbalance_30m: -0.01038
- tick_signed_count_1m: +0.01021
- tick_agg_arrival_60m: -0.00996
- tick_trade_intensity_60m: -0.00773

## Final-test volatility-regime breakdown

| Regime (30m realized vol) | Contracts | Tick log loss | Tick Brier | Realized up frequency |
|---|---:|---:|---:|---:|
| low | 959 | 0.6952 | 0.2510 | 52.3% |
| medium | 810 | 0.6919 | 0.2494 | 47.5% |
| high | 476 | 0.6939 | 0.2504 | 50.4% |

Interpretation: only claim a tick upgrade if it improves both log loss and Brier versus the bar-only model on this untouched test. Otherwise its value is data plumbing for the next iteration, not trading evidence.

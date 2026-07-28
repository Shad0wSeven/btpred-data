# 15-minute BTC up/down fair-mid study

## Contract definition

For each origin minute t, the YES contract settles at $1 if BTCFDUSD close[t+15m] > close[t], else $0. The quoted fair midpoint is `100 x P(up)` cents before fees, spread, and settlement-specific rules.

## Continuous PDF

A regularized logistic model maps the last two hours of causal market features to P(up). A Gaussian kernel density of 15-minute returns from the matching trailing-30m volatility regime is exponentially tilted until its integrated mass above zero equals that probability. Thus the PDF and binary midpoint are internally consistent.

## Strict walk-forward result

Data: 2026-04-01 through 2026-07-26. Training first 70%, calibration/tuning next 10%, final 20% untouched. Evaluation uses non-overlapping 15-minute contracts.

| Model | Log loss | Brier score | Quoted outside 45-55c | Directional hit rate when quoted |
|---|---:|---:|---:|---:|
| constant prior | 0.6932 | 0.2500 | 0.0% | 49.8% |
| global logistic | 0.6938 | 0.2503 | 0.0% | 49.8% |
| selected global logistic | 0.6938 | 0.2503 | 0.0% | 49.8% |

Selected model: global logistic; L2 regularization=0.3. The regime model is only used if it wins on the calibration period.

## Regimes and feature selection

Volatility regimes are trailing 30-minute realized-volatility terciles fixed from the training data. The most influential standardized feature coefficients are:

- taker_imbalance_120m: +0.1509
- taker_imbalance_60m: +0.0687
- taker_imbalance_15m: -0.0277
- log_quote_volume_60m: -0.0033
- log_quote_volume_120m: -0.0016
- return_5m_bps: -0.0015
- realized_vol_5m_bps: +0.0015
- realized_vol_30m_bps: +0.0012

## Latest archived forward quote

Latest data origin: 2026-07-26T23:59:00+00:00; settlement: 2026-07-27T00:14:00+00:00.
- Spot reference: $65,458.37
- Volatility regime: 1 (0=low, 2=high)
- Fair YES/UP midpoint: **48.3 cents**
- Fair NO/DOWN midpoint: **51.7 cents**
- KDE bandwidth: 2.83 bps; exponential-tilt parameter: -0.0018

## Calibration on final test

| Predicted range | Contracts | Mean predicted P(up) | Realized up frequency |
|---|---:|---:|---:|
| 45%-50% | 2245 | 48.3% | 50.2% |

The model is a fair-value estimator, not a tradable strategy. A real contract needs the venue's precise index, cutoff rule, fees, and available bid/ask. Only trade when the executable price clears an estimated edge after all costs; a midpoint alone is not evidence of edge.

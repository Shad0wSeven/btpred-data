# Hourly BTCFDUSD naive forecast backtest

Source: 3 monthly Binance 1-minute archives, aggregated to 2184 UTC hourly bars.

Forecast target: next hour's close. Holdout: final 30 days. All signals are lagged to the forecast origin.

| Model | Holdout MAE (USD) | Holdout RMSE (USD) | Direction accuracy |
|---|---:|---:|---:|
| last_close | 238.96 | 357.63 | n/a |
| same_hour_yesterday | 1199.17 | 1543.20 | 50.9% |
| sma_24 | 666.44 | 898.14 | 52.6% |
| momentum_24 | 246.74 | 363.89 | 50.1% |
| signal_ridge | 239.60 | 358.42 | 48.1% |

Signals in `signal_ridge`: current 1h return, 6h/24h momentum, trailing 24h return volatility, quote-volume surprise vs. the preceding 24h, hourly high-low range, and taker-buy quote-volume ratio. This is a baseline comparison, not an investable strategy.

# Conditional Gaussian PDF for a 15-minute BTC contract

The model predicts the mean and standard deviation of the 15-minute log return. For spot S and contract strike K:

`P(YES) = 1 - Phi((10,000*log(K/S) - mu_bps) / sigma_bps)`

Train: through 2025-09. Conditional variance fit: 2025 Q4. Mean/dispersion calibration: 2026 Q1. Final test: 2026-04 onward, non-overlapping 15-minute contracts.

| Probability model | Brier |
|---|---:|
| constant training prior | 0.250035 |
| raw conditional Gaussian | 0.250433 |
| Brier-calibrated Gaussian | 0.249958 |
| density-calibrated Gaussian | 0.249963 |

Brier calibration: mean shrinkage **0.95**, sigma multiplier **3.90**.
Density calibration: mean shrinkage **0.40**, sigma multiplier **2.75**.
Continuous Gaussian NLL: **4.2950**.
Nominal 80% interval empirical coverage: **82.67%**.
Median predicted 15-minute sigma: **15.03 bps**.

## Brier by long-term regime

| Volatility | 24h trend | Contracts | Gaussian Brier |
|---|---|---:|---:|
| low | down/flat | 2657 | 0.249981 |
| low | up | 2515 | 0.249898 |
| medium | down/flat | 1989 | 0.250138 |
| medium | up | 2072 | 0.249892 |
| high | down/flat | 1031 | 0.249773 |
| high | up | 967 | 0.250082 |

The CSV exposes a complete Gaussian at each origin: mean, sigma, 10th/90th percentile terminal prices, and the CDF-derived YES midpoint. A Kalshi contract with K different from current spot uses the same PDF with the actual log(K/S) threshold.

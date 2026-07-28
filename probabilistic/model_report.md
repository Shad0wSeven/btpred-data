# Two-hour, multi-horizon probabilistic BTCFDUSD model

A three-component Gaussian mixture-density network receives causal summaries of the prior 120 one-minute bars and a requested horizon. It is trained with negative log likelihood, so it learns both conditional mean and uncertainty. Train/test split is chronological: first 80% train, final 20% test.

| Horizon | MDN NLL | Volatility-baseline NLL | Median forecast MAE (per mille) | 80% interval coverage |
|---:|---:|---:|---:|---:|
| 1m | 1.051 | 0.768 | 0.394 | 97.8% |
| 5m | 1.562 | 1.588 | 0.875 | 91.2% |
| 15m | 2.056 | 2.142 | 1.522 | 83.3% |
| 30m | 2.425 | 2.499 | 2.174 | 78.4% |
| 60m | 2.795 | 2.883 | 3.061 | 77.3% |
| 120m | 3.173 | 3.285 | 4.330 | 81.0% |

The baseline is a zero-return Gaussian with volatility estimated from the preceding 120 minutes. Ideal 80% coverage is near 80%; NLL is the primary distributional score (lower is better). Forecast outputs contain 10th, 50th, and 90th percentiles for every minute through the 120-minute horizon at every test-hour origin.

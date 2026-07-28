# Kalshi KXBTC15M market Brier benchmark

The 15-minute observation uses the opening midpoint of Kalshi's first one-minute YES bid/ask candle. Later observations use the latest candle-closing midpoint available at that horizon. If both sides are unavailable, the last trade is used. Outcomes are official settled YES/NO results.

| Minutes before close | Markets | Brier | Log loss | Mean spread | 95% bootstrap Brier interval |
|---:|---:|---:|---:|---:|---:|
| 15m | 300 | 0.251009 | 0.695252 | 96.81% | [0.246565, 0.255568] |
| 14m | 300 | 0.243066 | 0.679852 | 1.04% | [0.229598, 0.256850] |
| 10m | 300 | 0.194520 | 0.572173 | 0.97% | [0.174668, 0.215745] |
| 5m | 300 | 0.111751 | 0.359886 | 0.67% | [0.091497, 0.134322] |
| 2m | 300 | 0.050392 | 0.170353 | 0.37% | [0.034854, 0.067760] |
| 1m | 300 | 0.026597 | 0.090537 | 0.27% | [0.015446, 0.040712] |

## Same-window head-to-head at contract open

Matched contracts: 191.
Our long-regime model Brier: **0.252912**.
Kalshi opening-midpoint Brier: **0.249538**.
Our loss minus Kalshi loss: **0.003375**; 95% market bootstrap interval **[-0.004122, 0.010934]**.

The interval crossing zero means this 191-market overlap is not yet large enough to establish the gap statistically, despite the sizable point estimate.

The 15-minute opening book is effectively unformed: its average spread is 96.81%, so its midpoint is approximately a non-executable 50/50 placeholder. By 14 minutes remaining, the mean spread contracts to 1.04% and Kalshi's Brier improves to 0.243066.

Market metadata requested: 300. Markets with at least one scored horizon: 300. Endpoint failures after retries: 0.

Interpretation: compare our model at contract open with Kalshi's 15-minute row. The 14-minute row already includes one minute of market information. Later rows have more information and should naturally score better. This is a market-probability benchmark, not a fill simulation; crossing the spread and fees requires additional edge.

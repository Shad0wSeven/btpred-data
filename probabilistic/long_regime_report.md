# Long-history nonlinear regime model

History: 2023-08-04 through 2026-07-26. Train: through 2025-09-30. Calibration/blending: 2025 Q4. Validation/model selection: 2026 Q1. Final test: 2026-04-01 onward, non-overlapping 15-minute contracts.

| Model | Brier | Log loss |
|---|---:|---:|
| constant training prior | 0.250035 | 0.693217 |
| histogram gradient boosting | 0.251314 | 0.695920 |
| extra trees | 0.249491 | 0.692133 |
| validation-selected blend | 0.249659 | 0.692474 |
| Platt-calibrated blend | 0.250228 | 0.693648 |
| isotonic-calibrated blend | 0.251898 | 0.702043 |
| volatility/trend regime experts | 0.250225 | 0.694281 |

Validation-selected final model: **extra trees**.
Q4 blend weight on histogram boosting: **0.25** (remainder extra trees).
Brier skill versus training prior: **0.217%**.
Daily-block bootstrap Brier improvement (baseline - model), 95% interval: **[-0.000163, 0.001234]**; median 0.000573.

A positive interval entirely above zero would support a statistically stable improvement. An interval crossing zero means the apparent gain is not reliable.

## Final-test regime performance

| Volatility | 24h trend | Contracts | Model Brier | Prior Brier | Brier skill |
|---|---|---:|---:|---:|---:|
| low | down/flat | 2657 | 0.249601 | 0.250016 | 0.17% |
| low | up | 2515 | 0.248684 | 0.250041 | 0.54% |
| medium | down/flat | 1989 | 0.249272 | 0.249970 | 0.28% |
| medium | up | 2072 | 0.250286 | 0.249981 | -0.12% |
| high | down/flat | 1031 | 0.250141 | 0.250183 | 0.02% |
| high | up | 967 | 0.249347 | 0.250162 | 0.33% |

## Extra-trees feature importance

- semivol_skew_60m: 0.0774
- tod_cos: 0.0573
- dow_sin: 0.0531
- tod_sin: 0.0520
- dow_cos: 0.0459
- return_1440m_bps: 0.0442
- return_120m_bps: 0.0340
- return_60m_bps: 0.0311
- return_30m_bps: 0.0303
- return_360m_bps: 0.0299
- return_15m_bps: 0.0288
- vol_10080m_bps: 0.0277
- semivol_skew_360m: 0.0277
- vol_ratio_1d_7d: 0.0256
- return_10080m_bps: 0.0238

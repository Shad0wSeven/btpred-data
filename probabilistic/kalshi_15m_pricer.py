#!/usr/bin/env python3
"""Price a 15-minute BTCFDUSD up/down contract from a continuous PDF.

The binary fair midpoint is P(log(C[t+15]/C[t]) > 0) * 100. A ridge-logistic
model estimates that probability from causal two-hour features. A regime-specific
Gaussian-KDE return density is exponentially tilted to exactly match that
probability, giving a coherent continuous 15-minute PDF and binary midpoint.
"""
import csv
import glob
import math
import os
import zipfile
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, ndtr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
RNG = np.random.default_rng(7)


def load_bars():
    paths = sorted(glob.glob(os.path.join(ROOT, "spot", "BTCFDUSD-1m-*.zip"))) + sorted(glob.glob(os.path.join(ROOT, "spot", "daily_2026_07", "*.zip")))
    rows = []
    for path in paths:
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as raw:
            for row in csv.reader(line.decode("utf-8") for line in raw):
                stamp = int(row[0])
                if stamp > 100_000_000_000_000:
                    stamp //= 1000
                rows.append((stamp, float(row[2]), float(row[3]), float(row[4]), float(row[7]), float(row[10])))
    # Daily July data and monthly data do not overlap; dedupe defensively.
    return sorted({row[0]: row for row in rows}.values())


FEATURE_NAMES = []


def make_features(high, low, close, quote_volume, buy_quote, origins):
    global FEATURE_NAMES
    log_price = np.log(close)
    r = np.diff(log_price, prepend=log_price[0]) * 10_000.0  # bps
    logv = np.log1p(quote_volume)
    imbalance = np.divide(buy_quote, quote_volume, out=np.full(len(close), 0.5), where=quote_volume > 0) - 0.5
    intrarange = np.log(high / low) * 10_000.0
    values, names = [], []
    for w in (1, 5, 15, 30, 60, 120):
        starts = origins - w + 1
        values.append((log_price[origins] - log_price[starts]) * 10_000.0); names.append(f"return_{w}m_bps")
        rs = np.array([r[s:i + 1] for s, i in zip(starts, origins)])
        values.append(rs.std(axis=1)); names.append(f"realized_vol_{w}m_bps")
    for w in (15, 60, 120):
        starts = origins - w + 1
        values.append(np.array([logv[s:i + 1].mean() for s, i in zip(starts, origins)])); names.append(f"log_quote_volume_{w}m")
        values.append(np.array([imbalance[s:i + 1].mean() for s, i in zip(starts, origins)])); names.append(f"taker_imbalance_{w}m")
        values.append(np.array([intrarange[s:i + 1].mean() for s, i in zip(starts, origins)])); names.append(f"range_{w}m_bps")
    FEATURE_NAMES = names
    return np.column_stack(values), r


def fit_logit(x, y, l2):
    # Intercept is not regularized. L2 reduces unstable high-frequency factors.
    design = np.column_stack((np.ones(len(x)), x))
    def objective(beta):
        z = design @ beta
        loss = np.mean(np.logaddexp(0, z) - y * z) + 0.5 * l2 * np.sum(beta[1:] ** 2)
        gradient = design.T @ (expit(z) - y) / len(y)
        gradient[1:] += l2 * beta[1:]
        return loss, gradient
    result = minimize(objective, np.zeros(design.shape[1]), jac=True, method="L-BFGS-B", options={"maxiter": 300})
    if not result.success:
        raise RuntimeError(result.message)
    return result.x


def predict(beta, x):
    return expit(np.column_stack((np.ones(len(x)), x)) @ beta)


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def calibration_table(p, y):
    rows = []
    for lo, hi in zip(np.arange(0.35, 0.65, 0.05), np.arange(0.40, 0.70, 0.05)):
        take = (p >= lo) & (p < hi)
        if take.sum() >= 20:
            rows.append((lo, hi, int(take.sum()), float(p[take].mean()), float(y[take].mean())))
    return rows


def kde_tilt(samples, target_prob, grid):
    """KDE f0(r), tilted f(r) proportional to exp(theta*r) f0(r)."""
    samples = np.asarray(samples)
    if len(samples) > 12_000:
        samples = RNG.choice(samples, 12_000, replace=False)
    bandwidth = max(0.5, 1.06 * np.std(samples, ddof=1) * len(samples) ** (-0.2))
    def probability(theta):
        weight_log = theta * samples + 0.5 * (theta * bandwidth) ** 2
        weight_log -= weight_log.max()
        weight = np.exp(weight_log); weight /= weight.sum()
        return float(np.sum(weight * ndtr((samples + theta * bandwidth ** 2) / bandwidth))), weight
    lo, hi = -0.4, 0.4
    for _ in range(60):
        mid = (lo + hi) / 2
        if probability(mid)[0] < target_prob: lo = mid
        else: hi = mid
    theta = (lo + hi) / 2
    _, weights = probability(theta)
    centers = samples + theta * bandwidth ** 2
    density = np.empty(len(grid))
    for start in range(0, len(grid), 100):
        g = grid[start:start + 100, None]
        density[start:start + 100] = (np.exp(-0.5 * ((g - centers) / bandwidth) ** 2) @ weights) / (bandwidth * math.sqrt(2 * math.pi))
    return density, bandwidth, theta


def main():
    bars = load_bars()
    stamps = np.array([x[0] for x in bars], dtype=np.int64)
    high, low, close, volume, buy = (np.array([x[i] for x in bars]) for i in range(1, 6))
    origins = np.arange(120, len(close) - 15)
    features, minute_returns = make_features(high, low, close, volume, buy, origins)
    target_return = np.log(close[origins + 15] / close[origins]) * 10_000.0
    target = (target_return > 0).astype(float)
    # Walk forward: training -> tuning/calibration -> final untouched test.
    n = len(origins); train_end, calibration_end = int(n * .70), int(n * .80)
    train, calibration, test = np.arange(train_end), np.arange(train_end, calibration_end), np.arange(calibration_end, n)
    mu, sd = features[train].mean(axis=0), features[train].std(axis=0); sd[sd < 1e-8] = 1
    x = (features - mu) / sd
    candidates = (0.003, 0.01, 0.03, 0.1, 0.3)
    fitted = [(l2, fit_logit(x[train], target[train], l2)) for l2 in candidates]
    l2, beta = min(fitted, key=lambda item: logloss(predict(item[1], x[calibration]), target[calibration]))
    raw_calibration = predict(beta, x[calibration])
    # Platt calibration on a held-out chronological slice, not the final test.
    cal_beta = fit_logit(np.log(raw_calibration / (1 - raw_calibration))[:, None], target[calibration], 0.03)
    def calibrated(p):
        q = np.clip(p, 1e-5, 1 - 1e-5)
        return predict(cal_beta, np.log(q / (1 - q))[:, None])

    global_test = calibrated(predict(beta, x[test]))
    # Regimes: fixed from training distribution, then separate regularized models.
    vol_column = FEATURE_NAMES.index("realized_vol_30m_bps")
    thresholds = np.quantile(features[train, vol_column], (1 / 3, 2 / 3))
    regime = np.digitize(features[:, vol_column], thresholds)
    regime_probs = np.zeros(len(test))
    regime_betas = {}
    for bucket in range(3):
        idx = train[regime[train] == bucket]
        regime_betas[bucket] = fit_logit(x[idx], target[idx], l2)
        mask = regime[test] == bucket
        regime_probs[mask] = calibrated(predict(regime_betas[bucket], x[test][mask]))
    # Choose the simpler global model unless regimes prove better on calibration.
    global_cal = calibrated(predict(beta, x[calibration]))
    regime_cal = np.zeros(len(calibration))
    for bucket, model in regime_betas.items():
        mask = regime[calibration] == bucket
        regime_cal[mask] = calibrated(predict(model, x[calibration][mask]))
    use_regimes = logloss(regime_cal, target[calibration]) + 0.0005 < logloss(global_cal, target[calibration])
    selected_test = regime_probs if use_regimes else global_test
    prior = float(target[train].mean())

    # Evaluate distinct 15m contracts to avoid showing hundreds of overlapping bets.
    independent = np.arange(0, len(test), 15)
    results = [("constant prior", np.full(len(independent), prior)), ("global logistic", global_test[independent]), ("regime logistic" if use_regimes else "selected global logistic", selected_test[independent])]
    metrics = [(name, logloss(p, target[test][independent]), brier(p, target[test][independent]), float(np.mean((p >= .55) | (p <= .45))), float(np.mean((p >= .55) == (target[test][independent] == 1)))) for name, p in results]

    # Retrain on all available history for the forward quote, retaining the selected structure.
    all_mu, all_sd = features.mean(axis=0), features.std(axis=0); all_sd[all_sd < 1e-8] = 1
    all_x = (features - all_mu) / all_sd
    full_global = fit_logit(all_x, target, l2)
    current_origin = len(close) - 1
    current_features, _ = make_features(high, low, close, volume, buy, np.array([current_origin]))
    current_x = (current_features - all_mu) / all_sd
    current_raw = predict(full_global, current_x)[0]
    current_prob = calibrated(np.array([current_raw]))[0]
    # Use the matching historical volatility regime for the base return distribution.
    all_regime = np.digitize(features[:, vol_column], thresholds)
    current_regime = int(np.digitize(current_features[0, vol_column], thresholds))
    samples = target_return[all_regime == current_regime]
    grid = np.linspace(-160, 160, 641)  # 15-minute return in bps
    density, bandwidth, theta = kde_tilt(samples, current_prob, grid)
    next_stamp = stamps[current_origin] + 15 * 60_000
    forecast_path = os.path.join(HERE, "next_15m_pdf.csv")
    with open(forecast_path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["forecast_origin_utc", "contract_settlement_utc", "return_bps", "price", "pdf_per_bps", "fair_up_mid_cents"])
        for r, d in zip(grid, density):
            writer.writerow([datetime.fromtimestamp(stamps[current_origin] / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(next_stamp / 1000, timezone.utc).isoformat(), r, close[current_origin] * math.exp(r / 10_000), d, current_prob * 100])
    with open(os.path.join(HERE, "kalshi_midpoint_backtest.csv"), "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["origin_utc", "actual_up", "actual_return_bps", "global_up_probability", "selected_up_probability", "selected_mid_cents", "volatility_regime"])
        for j in independent:
            i = test[j]
            writer.writerow([datetime.fromtimestamp(stamps[origins[i]] / 1000, timezone.utc).isoformat(), int(target[origins[i] - origins[0]]), target_return[i], global_test[j], selected_test[j], selected_test[j] * 100, int(regime[i])])
    coef = beta[1:] / sd
    ranked = sorted(zip(FEATURE_NAMES, coef), key=lambda item: abs(item[1]), reverse=True)[:8]
    cal_rows = calibration_table(selected_test[independent], target[test][independent])
    report = ["# 15-minute BTC up/down fair-mid study", "", "## Contract definition", "", "For each origin minute t, the YES contract settles at $1 if BTCFDUSD close[t+15m] > close[t], else $0. The quoted fair midpoint is `100 x P(up)` cents before fees, spread, and settlement-specific rules.", "", "## Continuous PDF", "", "A regularized logistic model maps the last two hours of causal market features to P(up). A Gaussian kernel density of 15-minute returns from the matching trailing-30m volatility regime is exponentially tilted until its integrated mass above zero equals that probability. Thus the PDF and binary midpoint are internally consistent.", "", "## Strict walk-forward result", "", f"Data: {datetime.fromtimestamp(stamps[0]/1000, timezone.utc).date()} through {datetime.fromtimestamp(stamps[-1]/1000, timezone.utc).date()}. Training first 70%, calibration/tuning next 10%, final 20% untouched. Evaluation uses non-overlapping 15-minute contracts.", "", "| Model | Log loss | Brier score | Quoted outside 45-55c | Directional hit rate when quoted |", "|---|---:|---:|---:|---:|"]
    for name, ll, br, activity, hit in metrics:
        report.append(f"| {name} | {ll:.4f} | {br:.4f} | {activity:.1%} | {hit:.1%} |")
    report += ["", f"Selected model: {'volatility-regime logistic' if use_regimes else 'global logistic'}; L2 regularization={l2}. The regime model is only used if it wins on the calibration period.", "", "## Regimes and feature selection", "", "Volatility regimes are trailing 30-minute realized-volatility terciles fixed from the training data. The most influential standardized feature coefficients are:", ""]
    for name, weight in ranked:
        report.append(f"- {name}: {weight:+.4f}")
    report += ["", "## Latest archived forward quote", "", f"Latest data origin: {datetime.fromtimestamp(stamps[current_origin]/1000, timezone.utc).isoformat()}; settlement: {datetime.fromtimestamp(next_stamp/1000, timezone.utc).isoformat()}.", f"- Spot reference: ${close[current_origin]:,.2f}", f"- Volatility regime: {current_regime} (0=low, 2=high)", f"- Fair YES/UP midpoint: **{current_prob * 100:.1f} cents**", f"- Fair NO/DOWN midpoint: **{(1-current_prob) * 100:.1f} cents**", f"- KDE bandwidth: {bandwidth:.2f} bps; exponential-tilt parameter: {theta:.4f}", "", "## Calibration on final test", "", "| Predicted range | Contracts | Mean predicted P(up) | Realized up frequency |", "|---|---:|---:|---:|"]
    for lo, hi, count, predicted, realized in cal_rows:
        report.append(f"| {lo:.0%}-{hi:.0%} | {count} | {predicted:.1%} | {realized:.1%} |")
    report += ["", "The model is a fair-value estimator, not a tradable strategy. A real contract needs the venue's precise index, cutoff rule, fees, and available bid/ask. Only trade when the executable price clears an estimated edge after all costs; a midpoint alone is not evidence of edge."]
    with open(os.path.join(HERE, "kalshi_pricing_report.md"), "w") as handle:
        handle.write("\n".join(report) + "\n")


if __name__ == "__main__":
    main()

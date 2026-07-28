#!/usr/bin/env python3
"""Conditional Gaussian return PDF and implied Kalshi-style YES probability."""
import csv
import math
import os
from datetime import datetime, timezone

import numpy as np
from scipy.special import ndtr
from sklearn.ensemble import ExtraTreesRegressor

import long_regime_models as data

HERE = os.path.dirname(os.path.abspath(__file__))


def brier(probability, outcome):
    return float(np.mean((probability - outcome) ** 2))


def gaussian_nll(actual, mean, sigma):
    z = (actual - mean) / sigma
    return float(np.mean(.5 * z*z + np.log(sigma) + .5*math.log(2*math.pi)))


def implied_yes_probability(mean_bps, sigma_bps, spot, strike):
    """P(terminal price > strike) under log-return N(mean, sigma)."""
    threshold_bps = np.log(np.asarray(strike) / np.asarray(spot)) * 10_000
    return ndtr((mean_bps - threshold_bps) / sigma_bps)


def main():
    stamps, high, low, close, volume, buy = data.load_bars()
    origins = np.arange(10080, len(close) - 15, 5)
    continuous = (
        (stamps[origins] - stamps[origins-10080] == 10080*60_000) &
        (stamps[origins+15] - stamps[origins] == 15*60_000)
    )
    origins = origins[continuous]
    x, names = data.build_features(
        stamps, high, low, close, volume, buy, origins)
    returns = np.log(close[origins+15] / close[origins]) * 10_000
    outcome = (returns > 0).astype(float)

    train_cut = int(datetime(2025, 10, 1, tzinfo=timezone.utc).timestamp()*1000)
    scale_cut = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()*1000)
    validation_cut = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()*1000)
    train = stamps[origins] < train_cut
    scale_train = ((stamps[origins] >= train_cut) &
                   (stamps[origins] < scale_cut))
    validation = ((stamps[origins] >= scale_cut) &
                  (stamps[origins] < validation_cut))
    test_all = stamps[origins] >= validation_cut
    test_positions = np.flatnonzero(test_all)
    test_positions = test_positions[np.arange(len(test_positions)) % 3 == 0]

    mean_model = ExtraTreesRegressor(
        n_estimators=450, max_features=.7, min_samples_leaf=180,
        max_depth=14, n_jobs=-1, random_state=31)
    mean_model.fit(x[train], returns[train])
    mean_scale = mean_model.predict(x[scale_train])

    # Fit conditional residual variance on a later, unseen period.
    residual2 = (returns[scale_train] - mean_scale) ** 2
    variance_floor = np.quantile(residual2, .05)
    variance_model = ExtraTreesRegressor(
        n_estimators=350, max_features=.7, min_samples_leaf=120,
        max_depth=12, n_jobs=-1, random_state=37)
    variance_model.fit(x[scale_train],
                       np.log(residual2 + max(variance_floor, .05)))

    def distribution(indices):
        mu = mean_model.predict(x[indices])
        sigma = np.sqrt(np.maximum(
            np.exp(variance_model.predict(x[indices])) - variance_floor,
            .05))
        return mu, sigma

    mu_val, sigma_val = distribution(validation)
    # Q1 2026 chooses mean shrinkage and dispersion scale by Brier only.
    grid = []
    for mean_scale_factor in np.linspace(0, 1.5, 31):
        for sigma_factor in np.linspace(.6, 4.0, 69):
            probability = ndtr(
                mean_scale_factor*mu_val/(sigma_factor*sigma_val))
            grid.append((
                brier(probability, outcome[validation]),
                gaussian_nll(returns[validation],
                             mean_scale_factor*mu_val,
                             sigma_factor*sigma_val),
                mean_scale_factor, sigma_factor))
    _, _, brier_mean_factor, brier_sigma_factor = min(
        grid, key=lambda row: row[0])
    _, _, density_mean_factor, density_sigma_factor = min(
        grid, key=lambda row: row[1])

    base_mu_test, base_sigma_test = distribution(test_positions)
    brier_mu = base_mu_test*brier_mean_factor
    brier_sigma = base_sigma_test*brier_sigma_factor
    brier_probability = implied_yes_probability(
        brier_mu, brier_sigma, close[origins[test_positions]],
        close[origins[test_positions]])
    # Primary exported PDF is likelihood-calibrated for honest distribution width.
    mu_test = base_mu_test*density_mean_factor
    sigma_test = base_sigma_test*density_sigma_factor
    # Backtest contract strike equals its BTC price at the origin.
    probability = implied_yes_probability(
        mu_test, sigma_test, close[origins[test_positions]],
        close[origins[test_positions]])
    actual = returns[test_positions]
    y = outcome[test_positions]
    p10_return = mu_test - 1.2815515655*sigma_test
    p90_return = mu_test + 1.2815515655*sigma_test
    coverage = float(np.mean(
        (actual >= p10_return) & (actual <= p90_return)))

    prior = np.full(len(y), outcome[train].mean())
    raw_probability = implied_yes_probability(
        mean_model.predict(x[test_positions]),
        base_sigma_test,
        close[origins[test_positions]], close[origins[test_positions]])
    metrics = [
        ("constant training prior", brier(prior, y)),
        ("raw conditional Gaussian", brier(raw_probability, y)),
        ("Brier-calibrated Gaussian", brier(brier_probability, y)),
        ("density-calibrated Gaussian", brier(probability, y)),
    ]

    vcol = names.index("vol_1440m_bps")
    tcol = names.index("return_1440m_bps")
    vol_edges = np.quantile(x[train, vcol], [1/3, 2/3])
    trend_edge = np.median(x[train, tcol])
    regimes = (np.digitize(x[:, vcol], vol_edges)*2 +
               (x[:, tcol] > trend_edge))

    report = [
        "# Conditional Gaussian PDF for a 15-minute BTC contract",
        "",
        "The model predicts the mean and standard deviation of the 15-minute "
        "log return. For spot S and contract strike K:",
        "",
        "`P(YES) = 1 - Phi((10,000*log(K/S) - mu_bps) / sigma_bps)`",
        "",
        "Train: through 2025-09. Conditional variance fit: 2025 Q4. "
        "Mean/dispersion calibration: 2026 Q1. Final test: 2026-04 onward, "
        "non-overlapping 15-minute contracts.",
        "",
        "| Probability model | Brier |",
        "|---|---:|",
    ]
    for label, score in metrics:
        report.append(f"| {label} | {score:.6f} |")
    report += [
        "",
        f"Brier calibration: mean shrinkage **{brier_mean_factor:.2f}**, "
        f"sigma multiplier **{brier_sigma_factor:.2f}**.",
        f"Density calibration: mean shrinkage **{density_mean_factor:.2f}**, "
        f"sigma multiplier **{density_sigma_factor:.2f}**.",
        f"Continuous Gaussian NLL: **{gaussian_nll(actual, mu_test, sigma_test):.4f}**.",
        f"Nominal 80% interval empirical coverage: **{coverage:.2%}**.",
        f"Median predicted 15-minute sigma: **{np.median(sigma_test):.2f} bps**.",
        "",
        "## Brier by long-term regime",
        "",
        "| Volatility | 24h trend | Contracts | Gaussian Brier |",
        "|---|---|---:|---:|",
    ]
    test_regime = regimes[test_positions]
    for regime in range(6):
        take = test_regime == regime
        if np.any(take):
            report.append(
                f"| {('low','medium','high')[regime//2]} | "
                f"{('down/flat','up')[regime%2]} | {take.sum()} | "
                f"{brier(probability[take], y[take]):.6f} |")
    report += [
        "",
        "The CSV exposes a complete Gaussian at each origin: mean, sigma, "
        "10th/90th percentile terminal prices, and the CDF-derived YES midpoint. "
        "A Kalshi contract with K different from current spot uses the same PDF "
        "with the actual log(K/S) threshold.",
    ]
    with open(os.path.join(HERE, "gaussian_distribution_report.md"), "w") as h:
        h.write("\n".join(report) + "\n")
    with open(os.path.join(HERE, "gaussian_distribution_backtest.csv"),
              "w", newline="") as h:
        writer = csv.writer(h)
        writer.writerow([
            "origin_utc", "spot", "strike", "actual_terminal_price",
            "actual_return_bps", "gaussian_mean_bps", "gaussian_sigma_bps",
            "p10_terminal_price", "p90_terminal_price",
            "yes_probability", "yes_mid_cents", "actual_yes", "regime"])
        for j, pos in enumerate(test_positions):
            spot = close[origins[pos]]
            writer.writerow([
                datetime.fromtimestamp(
                    stamps[origins[pos]]/1000, timezone.utc).isoformat(),
                spot, spot, close[origins[pos]+15], actual[j],
                mu_test[j], sigma_test[j],
                spot*math.exp(p10_return[j]/10_000),
                spot*math.exp(p90_return[j]/10_000),
                probability[j], probability[j]*100, int(y[j]),
                int(test_regime[j])
            ])


if __name__ == "__main__":
    main()

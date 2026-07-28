#!/usr/bin/env python3
"""Long-history nonlinear and regime-expert models for 15m BTC up/down."""
import csv
import glob
import math
import os
import zipfile
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
RNG = np.random.default_rng(123)


def load_bars():
    paths = sorted(glob.glob(os.path.join(ROOT, "spot", "BTCFDUSD-1m-*.zip")))
    paths += sorted(glob.glob(os.path.join(ROOT, "spot", "daily_2026_07", "*.zip")))
    rows = {}
    for path in paths:
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as raw:
            for row in csv.reader(line.decode("utf-8") for line in raw):
                stamp = int(row[0])
                if stamp > 100_000_000_000_000:
                    stamp //= 1000
                rows[stamp] = (stamp, float(row[2]), float(row[3]), float(row[4]),
                               float(row[7]), float(row[10]))
    ordered = sorted(rows.values())
    return tuple(np.array([r[i] for r in ordered]) for i in range(6))


def window_mean(prefix, origins, width):
    return (prefix[origins + 1] - prefix[origins - width + 1]) / width


def build_features(stamps, high, low, close, quote_volume, buy_quote, origins):
    lp = np.log(close)
    r = np.diff(lp, prepend=lp[0]) * 10_000
    r2 = r * r
    downside2 = np.minimum(r, 0) ** 2
    upside2 = np.maximum(r, 0) ** 2
    lrng = np.log(high / low) * 10_000
    logvol = np.log1p(quote_volume)
    imbalance = np.divide(buy_quote, quote_volume,
                          out=np.full(len(close), .5), where=quote_volume > 0) - .5
    prefixes = [np.r_[0., np.cumsum(x)] for x in
                (r, r2, downside2, upside2, lrng, logvol, imbalance)]
    pr, pr2, pd2, pu2, prange, pvolume, pimb = prefixes
    values, names = [], []

    for w in (1, 5, 15, 30, 60, 120, 360, 1440, 10080):
        values.append((lp[origins] - lp[origins - w]) * 10_000)
        names.append(f"return_{w}m_bps")
    for w in (5, 15, 30, 60, 120, 360, 1440, 10080):
        mean_r = window_mean(pr, origins, w)
        variance = np.maximum(window_mean(pr2, origins, w) - mean_r ** 2, 0)
        values.append(np.sqrt(variance)); names.append(f"vol_{w}m_bps")
    for w in (60, 360, 1440, 10080):
        down = np.sqrt(window_mean(pd2, origins, w))
        up = np.sqrt(window_mean(pu2, origins, w))
        values.append(np.divide(down - up, down + up + 1e-8))
        names.append(f"semivol_skew_{w}m")
    for w in (15, 60, 120, 360, 1440):
        values.append(window_mean(prange, origins, w)); names.append(f"range_{w}m")
        values.append(window_mean(pvolume, origins, w)); names.append(f"log_volume_{w}m")
        values.append(window_mean(pimb, origins, w)); names.append(f"imbalance_{w}m")

    # Explicit regime ratios and calendar effects.
    v60 = np.sqrt(np.maximum(window_mean(pr2, origins, 60) -
                            window_mean(pr, origins, 60) ** 2, 0))
    v1440 = np.sqrt(np.maximum(window_mean(pr2, origins, 1440) -
                              window_mean(pr, origins, 1440) ** 2, 0))
    v10080 = np.sqrt(np.maximum(window_mean(pr2, origins, 10080) -
                               window_mean(pr, origins, 10080) ** 2, 0))
    values += [np.log1p(v60 / (v1440 + 1e-4)),
               np.log1p(v1440 / (v10080 + 1e-4))]
    names += ["vol_ratio_1h_1d", "vol_ratio_1d_7d"]
    minute_of_day = ((stamps[origins] // 60_000) % 1440).astype(float)
    day_of_week = ((stamps[origins] // 86_400_000 + 3) % 7).astype(float)
    values += [np.sin(2 * np.pi * minute_of_day / 1440),
               np.cos(2 * np.pi * minute_of_day / 1440),
               np.sin(2 * np.pi * day_of_week / 7),
               np.cos(2 * np.pi * day_of_week / 7)]
    names += ["tod_sin", "tod_cos", "dow_sin", "dow_cos"]
    return np.column_stack(values).astype(np.float32), names


def scores(name, p, y):
    p = np.clip(p, 1e-5, 1 - 1e-5)
    return name, brier_score_loss(y, p), log_loss(y, p)


def block_bootstrap_delta(p_model, p_base, y, blocks, repeats=1000):
    unique = np.unique(blocks)
    deltas = []
    for _ in range(repeats):
        selected = RNG.choice(unique, len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(blocks == block) for block in selected])
        deltas.append(np.mean((p_base[indices] - y[indices]) ** 2) -
                      np.mean((p_model[indices] - y[indices]) ** 2))
    return np.quantile(deltas, [.025, .5, .975])


def make_hist():
    return HistGradientBoostingClassifier(
        learning_rate=.035, max_iter=350, max_leaf_nodes=15,
        min_samples_leaf=250, l2_regularization=5.0,
        max_bins=127, early_stopping=True, random_state=11)


def main():
    stamps, high, low, close, volume, buy = load_bars()
    # Five-minute training grid; final scoring is non-overlapping every 15m.
    origins = np.arange(10080, len(close) - 15, 5)
    continuous = ((stamps[origins] - stamps[origins - 10080] == 10080 * 60_000) &
                  (stamps[origins + 15] - stamps[origins] == 15 * 60_000))
    origins = origins[continuous]
    x, names = build_features(stamps, high, low, close, volume, buy, origins)
    returns = np.log(close[origins + 15] / close[origins]) * 10_000
    y = (returns > 0).astype(np.int8)
    train_cut = int(datetime(2025, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
    calibration_cut = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    val_cut = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
    train = stamps[origins] < train_cut
    calibration = ((stamps[origins] >= train_cut) &
                   (stamps[origins] < calibration_cut))
    val = ((stamps[origins] >= calibration_cut) &
           (stamps[origins] < val_cut))
    test_all = stamps[origins] >= val_cut
    # Score distinct contracts only; training can use the denser grid.
    test_positions = np.flatnonzero(test_all)
    test_positions = test_positions[np.arange(len(test_positions)) % 3 == 0]

    hist = make_hist()
    hist.fit(x[train], y[train])
    p_hist_cal = hist.predict_proba(x[calibration])[:, 1]
    p_hist_val = hist.predict_proba(x[val])[:, 1]
    p_hist_test = hist.predict_proba(x[test_positions])[:, 1]

    extra = ExtraTreesClassifier(
        n_estimators=350, max_features=.65, min_samples_leaf=150,
        max_depth=14, n_jobs=-1, random_state=13, class_weight="balanced")
    extra.fit(x[train], y[train])
    p_extra_cal = extra.predict_proba(x[calibration])[:, 1]
    p_extra_val = extra.predict_proba(x[val])[:, 1]
    p_extra_test = extra.predict_proba(x[test_positions])[:, 1]

    # Blend and calibration are fit on Q4 2025; Q1 2026 selects the model.
    weights = np.linspace(0, 1, 21)
    weight = min(weights, key=lambda w: brier_score_loss(
        y[calibration], w * p_hist_cal + (1 - w) * p_extra_cal))
    p_blend_cal = weight * p_hist_cal + (1 - weight) * p_extra_cal
    p_blend_val = weight * p_hist_val + (1 - weight) * p_extra_val
    p_blend_test = weight * p_hist_test + (1 - weight) * p_extra_test
    calibrator = IsotonicRegression(y_min=.02, y_max=.98, out_of_bounds="clip")
    calibrator.fit(p_blend_cal, y[calibration])
    p_cal_val = calibrator.predict(p_blend_val)
    p_cal_test = calibrator.predict(p_blend_test)
    platt = LogisticRegression(C=1.0, max_iter=500)
    platt.fit(np.log(np.clip(p_blend_cal, 1e-5, 1-1e-5) /
                     np.clip(1-p_blend_cal, 1e-5, 1))[:, None],
              y[calibration])
    p_platt_val = platt.predict_proba(
        np.log(np.clip(p_blend_val, 1e-5, 1-1e-5) /
               np.clip(1-p_blend_val, 1e-5, 1))[:, None])[:, 1]
    p_platt_test = platt.predict_proba(
        np.log(np.clip(p_blend_test, 1e-5, 1-1e-5) /
               np.clip(1-p_blend_test, 1e-5, 1))[:, None])[:, 1]

    # Volatility/trend regime experts. Regime thresholds are training-only.
    vcol, trendcol = names.index("vol_1440m_bps"), names.index("return_1440m_bps")
    vol_edges = np.quantile(x[train, vcol], [1/3, 2/3])
    trend_edge = np.median(x[train, trendcol])
    regimes = np.digitize(x[:, vcol], vol_edges) * 2 + (x[:, trendcol] > trend_edge)
    p_regime_cal = np.zeros(calibration.sum())
    p_regime_val = np.zeros(val.sum())
    p_regime_test = np.zeros(len(test_positions))
    cal_indices = np.flatnonzero(calibration)
    val_indices = np.flatnonzero(val)
    for regime in range(6):
        train_regime = train & (regimes == regime)
        expert = make_hist()
        expert.fit(x[train_regime], y[train_regime])
        cmask = regimes[cal_indices] == regime
        vmask = regimes[val_indices] == regime
        tmask = regimes[test_positions] == regime
        p_regime_cal[cmask] = expert.predict_proba(x[cal_indices[cmask]])[:, 1]
        p_regime_val[vmask] = expert.predict_proba(x[val_indices[vmask]])[:, 1]
        p_regime_test[tmask] = expert.predict_proba(x[test_positions[tmask]])[:, 1]
    regime_cal = IsotonicRegression(y_min=.02, y_max=.98, out_of_bounds="clip")
    regime_cal.fit(p_regime_cal, y[calibration])
    p_regime_val = regime_cal.predict(p_regime_val)
    p_regime_test = regime_cal.predict(p_regime_test)

    yt = y[test_positions]
    prior = np.full(len(yt), y[train].mean())
    candidates = [
        scores("constant training prior", prior, yt),
        scores("histogram gradient boosting", p_hist_test, yt),
        scores("extra trees", p_extra_test, yt),
        scores("validation-selected blend", p_blend_test, yt),
        scores("Platt-calibrated blend", p_platt_test, yt),
        scores("isotonic-calibrated blend", p_cal_test, yt),
        scores("volatility/trend regime experts", p_regime_test, yt),
    ]
    # Final choice is fixed by validation Brier, then read once on test.
    val_candidates = {
        "histogram gradient boosting": p_hist_val,
        "extra trees": p_extra_val,
        "validation-selected blend": p_blend_val,
        "Platt-calibrated blend": p_platt_val,
        "isotonic-calibrated blend": p_cal_val,
        "volatility/trend regime experts": p_regime_val,
    }
    selected_name = min(val_candidates, key=lambda key: brier_score_loss(y[val], val_candidates[key]))
    selected_test = {
        "histogram gradient boosting": p_hist_test,
        "extra trees": p_extra_test,
        "validation-selected blend": p_blend_test,
        "Platt-calibrated blend": p_platt_test,
        "isotonic-calibrated blend": p_cal_test,
        "volatility/trend regime experts": p_regime_test,
    }[selected_name]
    blocks = (stamps[origins[test_positions]] // 86_400_000).astype(int)
    ci = block_bootstrap_delta(selected_test, prior, yt, blocks)
    skill = 1 - brier_score_loss(yt, selected_test) / brier_score_loss(yt, prior)

    importance = sorted(zip(names, extra.feature_importances_), key=lambda z: z[1], reverse=True)
    report = [
        "# Long-history nonlinear regime model",
        "",
        f"History: {datetime.fromtimestamp(stamps[0]/1000, timezone.utc).date()} through "
        f"{datetime.fromtimestamp(stamps[-1]/1000, timezone.utc).date()}. "
        "Train: through 2025-09-30. Calibration/blending: 2025 Q4. "
        "Validation/model selection: 2026 Q1. "
        "Final test: 2026-04-01 onward, non-overlapping 15-minute contracts.",
        "",
        "| Model | Brier | Log loss |",
        "|---|---:|---:|",
    ]
    for name, brier, ll in candidates:
        report.append(f"| {name} | {brier:.6f} | {ll:.6f} |")
    report += [
        "",
        f"Validation-selected final model: **{selected_name}**.",
        f"Q4 blend weight on histogram boosting: **{weight:.2f}** "
        f"(remainder extra trees).",
        f"Brier skill versus training prior: **{skill:.3%}**.",
        f"Daily-block bootstrap Brier improvement (baseline - model), "
        f"95% interval: **[{ci[0]:.6f}, {ci[2]:.6f}]**; median {ci[1]:.6f}.",
        "",
        "A positive interval entirely above zero would support a statistically stable "
        "improvement. An interval crossing zero means the apparent gain is not reliable.",
        "",
        "## Final-test regime performance",
        "",
        "| Volatility | 24h trend | Contracts | Model Brier | Prior Brier | Brier skill |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for regime in range(6):
        take = regimes[test_positions] == regime
        if not np.any(take):
            continue
        model_brier = brier_score_loss(yt[take], selected_test[take])
        prior_brier = brier_score_loss(yt[take], prior[take])
        regime_skill = 1 - model_brier / prior_brier
        report.append(
            f"| {('low', 'medium', 'high')[regime // 2]} | "
            f"{('down/flat', 'up')[regime % 2]} | {take.sum()} | "
            f"{model_brier:.6f} | {prior_brier:.6f} | {regime_skill:.2%} |")
    report += [
        "",
        "## Extra-trees feature importance",
        "",
    ]
    for name, value in importance[:15]:
        report.append(f"- {name}: {value:.4f}")
    with open(os.path.join(HERE, "long_regime_report.md"), "w") as handle:
        handle.write("\n".join(report) + "\n")
    with open(os.path.join(HERE, "long_regime_backtest.csv"), "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["origin_utc", "actual_up", "return_bps", "prior_probability",
                         "selected_probability", "selected_mid_cents", "regime"])
        for j, pos in enumerate(test_positions):
            writer.writerow([
                datetime.fromtimestamp(stamps[origins[pos]]/1000, timezone.utc).isoformat(),
                int(yt[j]), returns[pos], prior[j], selected_test[j],
                selected_test[j] * 100, int(regimes[pos])
            ])


if __name__ == "__main__":
    main()

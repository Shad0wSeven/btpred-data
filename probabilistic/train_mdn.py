#!/usr/bin/env python3
"""Multi-horizon BTCFDUSD mixture-density forecast using only NumPy.

At an origin minute t, the model sees summaries of the preceding 120 one-minute
bars plus requested horizon h (1..120 minutes). It returns a three-Gaussian
mixture for log(C[t+h]/C[t]), trained by negative log likelihood.  The output
therefore supplies a full conditional distribution at every requested horizon,
rather than just a point forecast.
"""
import csv
import glob
import math
import os
import zipfile
from datetime import datetime, timezone

import numpy as np
from scipy.special import erf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPOT = sorted(glob.glob(os.path.join(ROOT, "spot", "BTCFDUSD-1m-*.zip")))
HERE = os.path.dirname(os.path.abspath(__file__))
RNG = np.random.default_rng(42)


def load_data():
    rows = []
    for path in SPOT:
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as raw:
            for row in csv.reader(line.decode("utf-8") for line in raw):
                stamp = int(row[0])
                if stamp > 100_000_000_000_000:
                    stamp //= 1000
                rows.append((stamp, float(row[2]), float(row[3]), float(row[4]), float(row[7]), float(row[10])))
    rows.sort()
    stamps = np.array([x[0] for x in rows], dtype=np.int64)
    high, low, close = (np.array([x[i] for x in rows]) for i in (1, 2, 3))
    quote_volume, buy_quote = (np.array([x[i] for x in rows]) for i in (4, 5))
    return stamps, high, low, close, quote_volume, buy_quote


def features_for_origins(close, high, low, volume, buy_quote, origins):
    """Use the full prior two hours through multi-scale, causal summaries."""
    log_close = np.log(close)
    minute_return = np.diff(log_close, prepend=log_close[0]) * 1000.0
    log_volume = np.log1p(volume)
    order_imbalance = np.divide(buy_quote, volume, out=np.full(len(volume), 0.5), where=volume > 0) - 0.5
    intraminute_range = np.log(high / low) * 1000.0
    windows = (1, 2, 5, 10, 15, 30, 60, 90, 120)
    matrix = []
    for w in windows:
        # Origin itself is included: it is observable at the forecast origin.
        starts = origins - w + 1
        trend = log_close[origins] - log_close[starts]
        ret_window = np.array([minute_return[s:i + 1] for s, i in zip(starts, origins)])
        vol = ret_window.std(axis=1)
        matrix.extend((trend * 1000.0, vol))
    # Last-minute market state, and 2h volume / order-flow summaries.
    for w in (5, 30, 120):
        starts = origins - w + 1
        matrix.append(np.array([log_volume[s:i + 1].mean() for s, i in zip(starts, origins)]))
        matrix.append(np.array([order_imbalance[s:i + 1].mean() for s, i in zip(starts, origins)]))
        matrix.append(np.array([intraminute_range[s:i + 1].mean() for s, i in zip(starts, origins)]))
    return np.column_stack(matrix)


def softmax(x):
    x = x - x.max(axis=1, keepdims=True)
    ex = np.exp(x)
    return ex / ex.sum(axis=1, keepdims=True)


class MDN:
    def __init__(self, d, hidden=48, components=3):
        self.k = components
        self.w1 = RNG.normal(0, 1 / math.sqrt(d), (d, hidden))
        self.b1 = np.zeros(hidden)
        self.w2 = RNG.normal(0, 0.04, (hidden, components * 3))
        self.b2 = np.zeros(components * 3)
        self.params = [self.w1, self.b1, self.w2, self.b2]
        self.m = [np.zeros_like(p) for p in self.params]
        self.v = [np.zeros_like(p) for p in self.params]
        self.step = 0

    def forward(self, x):
        z = x @ self.w1 + self.b1
        h = np.tanh(z)
        raw = h @ self.w2 + self.b2
        logits, means, raw_scale = np.split(raw, 3, axis=1)
        log_scale = np.clip(raw_scale, -3.5, 4.0)
        scale = np.exp(log_scale) + 1e-4
        return z, h, logits, means, log_scale, scale

    def train_step(self, x, y, lr=0.0015):
        z, h, logits, means, log_scale, scale = self.forward(x)
        pi = softmax(logits)
        standardized = (y[:, None] - means) / scale
        log_component = np.log(pi + 1e-12) - log_scale - 0.5 * standardized ** 2 - 0.5 * math.log(2 * math.pi)
        maximum = log_component.max(axis=1, keepdims=True)
        log_prob = maximum[:, 0] + np.log(np.exp(log_component - maximum).sum(axis=1))
        responsibility = np.exp(log_component - log_prob[:, None])
        n = len(x)
        grad_logits = (pi - responsibility) / n
        grad_means = responsibility * (means - y[:, None]) / (scale ** 2) / n
        grad_log_scale = responsibility * (1 - standardized ** 2) / n
        grad_raw = np.concatenate((grad_logits, grad_means, grad_log_scale), axis=1)
        grad_w2 = h.T @ grad_raw
        grad_b2 = grad_raw.sum(axis=0)
        grad_h = grad_raw @ self.w2.T
        grad_z = grad_h * (1 - np.tanh(z) ** 2)
        gradients = [x.T @ grad_z, grad_z.sum(axis=0), grad_w2, grad_b2]
        self.step += 1
        for i, (param, grad) in enumerate(zip(self.params, gradients)):
            self.m[i] = 0.9 * self.m[i] + 0.1 * grad
            self.v[i] = 0.999 * self.v[i] + 0.001 * grad ** 2
            mhat = self.m[i] / (1 - 0.9 ** self.step)
            vhat = self.v[i] / (1 - 0.999 ** self.step)
            param -= lr * mhat / (np.sqrt(vhat) + 1e-8)
        return float(-log_prob.mean())

    def distribution(self, x):
        _, _, logits, means, _, scales = self.forward(x)
        return softmax(logits), means, scales


def mixture_quantile(weights, means, scales, q):
    lo = np.min(means - 8 * scales, axis=1)
    hi = np.max(means + 8 * scales, axis=1)
    for _ in range(45):
        mid = (lo + hi) / 2
        cdf = (weights * (0.5 * (1 + erf((mid[:, None] - means) / (scales * math.sqrt(2)))))).sum(axis=1)
        lo = np.where(cdf < q, mid, lo)
        hi = np.where(cdf < q, hi, mid)
    return (lo + hi) / 2


def nll(weights, means, scales, y):
    z = (y[:, None] - means) / scales
    component = np.log(weights + 1e-12) - np.log(scales) - 0.5 * z ** 2 - 0.5 * math.log(2 * math.pi)
    mx = component.max(axis=1, keepdims=True)
    return float(-(mx[:, 0] + np.log(np.exp(component - mx).sum(axis=1))).mean())


def main():
    stamps, high, low, close, volume, buy_quote = load_data()
    split = int(len(close) * 0.80)
    train_origins = np.arange(120, split - 120)
    test_origins = np.arange(split, len(close) - 120)
    x_train_base = features_for_origins(close, high, low, volume, buy_quote, train_origins)
    x_test_base = features_for_origins(close, high, low, volume, buy_quote, test_origins)
    mean, std = x_train_base.mean(axis=0), x_train_base.std(axis=0)
    std[std < 1e-8] = 1.0
    x_train_base = (x_train_base - mean) / std
    x_test_base = (x_test_base - mean) / std

    # Horizon is a model input, so one trained model handles every minute through 2h.
    model = MDN(x_train_base.shape[1] + 2)
    history = []
    for epoch in range(18):
        selected = RNG.choice(len(train_origins), size=min(32_768, len(train_origins)), replace=False)
        horizons = RNG.integers(1, 121, len(selected))
        x = np.column_stack((x_train_base[selected], horizons / 120.0, np.log(horizons) / math.log(120)))
        y = np.log(close[train_origins[selected] + horizons] / close[train_origins[selected]]) * 1000.0
        order = RNG.permutation(len(x))
        losses = []
        for start in range(0, len(x), 512):
            batch = order[start:start + 512]
            losses.append(model.train_step(x[batch], y[batch]))
        history.append(float(np.mean(losses)))
        print(f"epoch {epoch + 1:02d}/18 nll={history[-1]:.4f}")

    horizons = np.array([1, 5, 15, 30, 60, 120])
    all_rows, metrics = [], []
    for horizon in horizons:
        x = np.column_stack((x_test_base, np.full(len(test_origins), horizon / 120.0), np.full(len(test_origins), math.log(horizon) / math.log(120))))
        weights, means, scales = model.distribution(x)
        y = np.log(close[test_origins + horizon] / close[test_origins]) * 1000.0
        p10, p50, p90 = (mixture_quantile(weights, means, scales, q) for q in (0.10, 0.50, 0.90))
        baseline_sigma = np.array([np.std(np.log(close[i - 119:i + 1] / close[i - 120:i]) * 1000.0) * math.sqrt(horizon) for i in test_origins])
        baseline_sigma = np.maximum(baseline_sigma, 0.1)
        baseline_nll = float(np.mean(0.5 * (y / baseline_sigma) ** 2 + np.log(baseline_sigma) + 0.5 * math.log(2 * math.pi)))
        metrics.append((horizon, nll(weights, means, scales, y), baseline_nll, float(np.mean(np.abs(p50 - y))), float(np.mean((y >= p10) & (y <= p90)))))
    # Save every minute of the 2h distribution path at each test-hour origin.
    export_origins, export_features = test_origins[::60], x_test_base[::60]
    for horizon in range(1, 121):
        x = np.column_stack((export_features, np.full(len(export_origins), horizon / 120.0), np.full(len(export_origins), math.log(horizon) / math.log(120))))
        weights, means, scales = model.distribution(x)
        p10, p50, p90 = (mixture_quantile(weights, means, scales, q) for q in (0.10, 0.50, 0.90))
        for j, origin in enumerate(export_origins):
            all_rows.append([datetime.fromtimestamp(stamps[origin] / 1000, timezone.utc).isoformat(), horizon, close[origin], close[origin + horizon], p10[j], p50[j], p90[j], close[origin] * math.exp(p10[j] / 1000), close[origin] * math.exp(p50[j] / 1000), close[origin] * math.exp(p90[j] / 1000)])

    with open(os.path.join(HERE, "distribution_forecasts.csv"), "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["origin_utc", "horizon_minutes", "origin_price", "actual_price", "p10_return_per_mille", "p50_return_per_mille", "p90_return_per_mille", "p10_price", "p50_price", "p90_price"])
        writer.writerows(sorted(all_rows, key=lambda row: (row[0], row[1])))
    with open(os.path.join(HERE, "model_report.md"), "w") as handle:
        handle.write("# Two-hour, multi-horizon probabilistic BTCFDUSD model\n\n")
        handle.write("A three-component Gaussian mixture-density network receives causal summaries of the prior 120 one-minute bars and a requested horizon. It is trained with negative log likelihood, so it learns both conditional mean and uncertainty. Train/test split is chronological: first 80% train, final 20% test.\n\n")
        handle.write("| Horizon | MDN NLL | Volatility-baseline NLL | Median forecast MAE (per mille) | 80% interval coverage |\n|---:|---:|---:|---:|---:|\n")
        for horizon, model_nll, base_nll, mae, coverage in metrics:
            handle.write(f"| {horizon}m | {model_nll:.3f} | {base_nll:.3f} | {mae:.3f} | {coverage:.1%} |\n")
        handle.write("\nThe baseline is a zero-return Gaussian with volatility estimated from the preceding 120 minutes. Ideal 80% coverage is near 80%; NLL is the primary distributional score (lower is better). Forecast outputs contain 10th, 50th, and 90th percentiles for every minute through the 120-minute horizon at every test-hour origin.\n")
    np.savez(os.path.join(HERE, "mdn_parameters.npz"), mean=mean, std=std, w1=model.w1, b1=model.b1, w2=model.w2, b2=model.b2)


if __name__ == "__main__":
    main()

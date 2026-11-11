"""Synthetic proximity-probe vibration and FFT feature classification.

The plant simulator only emits overall vibration amplitude (um pk-pk). Diagnosis needs the
waveform, so this module synthesises shaft relative displacement x(t) for a 9000 rpm rotor
(1X = 150 Hz) with the classic signatures (API 670 probes; Bently and Hatch (2002)
"Fundamentals of Rotating Machinery Diagnostics"):

- unbalance: dominant 1X, circular orbit
- misalignment: strong 2X (and 3X), 1X phase shift between probes
- oil whirl: subsynchronous component near 0.43X to 0.48X
- rub: harmonics series plus 1/2X subharmonic, truncated waveform
- looseness: many harmonics, broadband floor

This is a teaching dataset with known ground truth. Real probe data has runout, slow-roll
vectors and speed changes that this does not model. Benchmarks against real bearing data
(CWRU, Paderborn) use the download scripts in analytics/benchmarks.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

CLASSES = ["normal", "unbalance", "misalignment", "oil_whirl", "rub", "looseness"]
FS = 5120.0  # Hz, typical portable analyser setting for a 150 Hz 1X
N = 2048


def waveform(kind: str, rng: np.random.Generator, rpm: float | None = None) -> np.ndarray:
    rpm = rpm if rpm is not None else rng.uniform(8200, 9400)
    f1 = rpm / 60
    t = np.arange(N) / FS
    ph = rng.uniform(0, 2 * np.pi, 8)
    a1 = rng.uniform(8, 14)
    x = a1 * np.sin(2 * np.pi * f1 * t + ph[0]) + 1.5 * np.sin(2 * np.pi * 2 * f1 * t + ph[1])
    if kind == "unbalance":
        x += rng.uniform(15, 30) * np.sin(2 * np.pi * f1 * t + ph[2])
    elif kind == "misalignment":
        x += rng.uniform(8, 18) * np.sin(2 * np.pi * 2 * f1 * t + ph[3]) + rng.uniform(2, 6) * np.sin(2 * np.pi * 3 * f1 * t)
    elif kind == "oil_whirl":
        x += rng.uniform(8, 20) * np.sin(2 * np.pi * rng.uniform(0.42, 0.48) * f1 * t + ph[4])
    elif kind == "rub":
        x += rng.uniform(4, 9) * np.sin(2 * np.pi * 0.5 * f1 * t + ph[5])
        for k in range(2, 6):
            x += rng.uniform(1, 4) / k * np.sin(2 * np.pi * k * f1 * t + ph[6])
        x = np.clip(x, None, np.quantile(x, rng.uniform(0.85, 0.95)))
    elif kind == "looseness":
        for k in range(2, 10):
            x += rng.uniform(1.5, 4) * np.sin(2 * np.pi * k * f1 * t + rng.uniform(0, 6.28))
        x += rng.normal(0, 2.5, N)
    return x + rng.normal(0, 1.0, N)


def features(x: np.ndarray, rpm: float) -> np.ndarray:
    """Order-domain features: amplitude at 0.4-0.5X, 1/2X, 1X..5X, broadband, crest, kurtosis."""
    f1 = rpm / 60
    w = np.hanning(len(x))
    spec = np.abs(np.fft.rfft((x - x.mean()) * w)) * 2 / w.sum()
    f = np.fft.rfftfreq(len(x), 1 / FS)

    def band(lo: float, hi: float) -> float:
        m = (f >= lo * f1) & (f <= hi * f1)
        return float(spec[m].max()) if m.any() else 0.0

    orders = [band(k - 0.05, k + 0.05) for k in (1, 2, 3, 4, 5)]
    sub = band(0.38, 0.49)
    half = band(0.49, 0.52)
    broad = float(np.median(spec[(f > 0.2 * f1) & (f < 10 * f1)]))
    rms = float(x.std())
    crest = float(np.max(np.abs(x - x.mean())) / rms)
    kurt = float(np.mean((x - x.mean()) ** 4) / rms**4)
    skew = float(np.mean((x - x.mean()) ** 3) / rms**3)
    return np.array([*orders, sub, half, broad, rms, crest, kurt, skew])


def dataset(n_per_class: int = 200, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    xs, ys = [], []
    for ci, c in enumerate(CLASSES):
        for _ in range(n_per_class):
            rpm = rng.uniform(8200, 9400)
            rpm_meas = rpm * (1 + rng.normal(0, 0.002))  # keyphasor speed is known well
            xs.append(features(waveform(c, rng, rpm), rpm_meas))
            ys.append(ci)
    return np.array(xs), np.array(ys)


def baseline_predict(x_feat: np.ndarray) -> np.ndarray:
    """Rule-based baseline: an analyst's chart (dominant spectral component)."""
    out = []
    for r in x_feat:
        o1, o2, o3, _, _, sub, half, broad, *_ = r
        if sub > 0.5 * o1:
            out.append(3)
        elif half > 2.0:
            out.append(4)
        elif broad > 0.6 or (o3 > 2 and r[3] > 1.5):
            out.append(5)
        elif o2 > 0.6 * o1:
            out.append(2)
        elif o1 > 20:
            out.append(1)
        else:
            out.append(0)
    return np.array(out)


def evaluate(seed: int = 0) -> dict[str, float]:
    x, y = dataset(seed=seed)
    xtr, xte, ytr, yte = train_test_split(x, y, test_size=0.3, random_state=seed, stratify=y)
    clf = RandomForestClassifier(n_estimators=200, random_state=seed).fit(xtr, ytr)
    yp = clf.predict(xte)
    yb = baseline_predict(xte)
    return {
        "rf_accuracy": float(accuracy_score(yte, yp)),
        "rf_macro_f1": float(f1_score(yte, yp, average="macro")),
        "rule_accuracy": float(accuracy_score(yte, yb)),
        "rule_macro_f1": float(f1_score(yte, yb, average="macro")),
    }

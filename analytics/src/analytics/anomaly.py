"""Early anomaly detection: PCA (Hotelling T2 and SPE) and an MSET-style similarity model.

PCA monitoring: Jackson (1991) A User's Guide to Principal Components; Qin (2003) "Statistical
process monitoring: basics and beyond", J. Chemometrics 17. Limits: T2 from the F distribution,
SPE from the Jackson-Mudholkar approximation, both at 99 percent.
MSET-style: nonparametric similarity-based estimation in the spirit of Gross et al. (1997)
and the Advanced Pattern Recognition products (SmartSignal, PRiSM); not the patented MSET
operator itself. Estimate = similarity-weighted average of remembered healthy states.
Alarm logic: k-of-n persistence filter, as deployed APR tools do, to trade delay for false alarms.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class Scaler:
    mu: np.ndarray
    sd: np.ndarray

    @classmethod
    def fit(cls, x: np.ndarray) -> Scaler:
        return cls(x.mean(0), np.maximum(x.std(0), 1e-6))

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mu) / self.sd


@dataclass
class PCAMonitor:
    scaler: Scaler
    p: np.ndarray  # loadings (m x a)
    lam: np.ndarray  # retained eigenvalues
    t2_lim: float
    spe_lim: float

    @classmethod
    def fit(cls, x: np.ndarray, var_explained: float = 0.9, alpha: float = 0.01) -> PCAMonitor:
        sc = Scaler.fit(x)
        z = sc(x)
        n = z.shape[0]
        eigval, eigvec = np.linalg.eigh(np.cov(z, rowvar=False))
        order = np.argsort(eigval)[::-1]
        eigval, eigvec = eigval[order], eigvec[:, order]
        a = int(np.searchsorted(np.cumsum(eigval) / eigval.sum(), var_explained) + 1)
        t2_lim = a * (n - 1) * (n + 1) / (n * (n - a)) * stats.f.ppf(1 - alpha, a, n - a)
        th = [np.sum(eigval[a:] ** i) for i in (1, 2, 3)]
        h0 = 1 - 2 * th[0] * th[2] / (3 * th[1] ** 2)
        c = stats.norm.ppf(1 - alpha)
        spe_lim = th[0] * (c * np.sqrt(2 * th[1] * h0**2) / th[0] + 1 + th[1] * h0 * (h0 - 1) / th[0] ** 2) ** (1 / h0)
        return cls(sc, eigvec[:, :a], eigval[:a], float(t2_lim), float(spe_lim))

    def scores(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        z = self.scaler(x)
        t = z @ self.p
        t2 = np.sum(t**2 / self.lam, axis=1)
        resid = z - t @ self.p.T
        return t2, np.sum(resid**2, axis=1)

    def flags(self, x: np.ndarray) -> np.ndarray:
        t2, spe = self.scores(x)
        return (t2 > self.t2_lim) | (spe > self.spe_lim)

    def contributions(self, x: np.ndarray) -> np.ndarray:
        """SPE contribution per variable (diagnosis: which sensor/variable deviates)."""
        z = self.scaler(x)
        resid = z - (z @ self.p) @ self.p.T
        return resid**2


@dataclass
class SimilarityModel:
    scaler: Scaler
    memory: np.ndarray
    bandwidth: float
    limit: float

    @classmethod
    def fit(cls, x: np.ndarray, n_mem: int = 400, alpha: float = 0.01) -> SimilarityModel:
        sc = Scaler.fit(x)
        z = sc(x)
        idx = np.linspace(0, len(z) - 1, min(n_mem, len(z))).astype(int)
        mem = z[idx]
        d = np.linalg.norm(mem[:, None] - mem[None], axis=2)
        np.fill_diagonal(d, np.inf)
        bw = 2.0 * float(np.median(np.sort(d, axis=1)[:, :5]))  # local kernel: a few nearest neighbours
        model = cls(sc, mem, bw, 0.0)
        r = model.residual(x)
        model.limit = float(np.quantile(r, 1 - alpha))
        return model

    def residual(self, x: np.ndarray) -> np.ndarray:
        z = self.scaler(x)
        d = np.linalg.norm(z[:, None] - self.memory[None], axis=2)
        w = np.exp(-((d / self.bandwidth) ** 2))
        w /= np.maximum(w.sum(1, keepdims=True), 1e-12)
        est = w @ self.memory
        return np.linalg.norm(z - est, axis=1)

    def flags(self, x: np.ndarray) -> np.ndarray:
        return self.residual(x) > self.limit


def persistence(flags: np.ndarray, k: int = 3, n: int = 5) -> np.ndarray:
    """Alarm when at least k of the last n samples are flagged."""
    c = np.convolve(flags.astype(int), np.ones(n, dtype=int), mode="full")[: len(flags)]
    return c >= k


def metrics(alarm: np.ndarray, label: np.ndarray, t: np.ndarray) -> dict[str, float]:
    normal = label == 0
    far = float(alarm[normal].mean()) if normal.any() else float("nan")
    if label.any():
        onset = t[np.argmax(label)]
        hits = np.where(alarm & (label == 1))[0]
        delay = float(t[hits[0]] - onset) if hits.size else float("inf")
        det = float(alarm[label == 1].mean())
    else:
        delay, det = float("nan"), float("nan")
    return {"false_alarm_rate": far, "detection_delay_s": delay, "detection_rate": det}

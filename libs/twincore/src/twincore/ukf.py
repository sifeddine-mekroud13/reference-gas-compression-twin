"""Unscented Kalman Filter (scaled sigma points) for joint degradation-parameter estimation.

State x = [f_head, f_eta, f_ua], random-walk process model (slow drift).
Measurements y = [pressure ratio, discharge temperature K, motor power W, cooler outlet K],
predicted by the TwinModel from measured inputs (flow, speed, suction p and T, ambient, fans).
Sources: Julier and Uhlmann (1997); Wan and van der Merwe (2000), "The unscented Kalman
filter for nonlinear estimation", IEEE AS-SPCC. Choice over EKF: ADR 0009.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

Arr = NDArray[np.float64]


@dataclass
class UKF:
    x: Arr
    P: Arr
    Q: Arr
    R: Arr
    alpha: float = 0.5
    beta: float = 2.0
    kappa: float = 0.0
    lower: Arr = field(default_factory=lambda: np.array([0.7, 0.7, 0.3]))
    upper: Arr = field(default_factory=lambda: np.array([1.1, 1.1, 1.6]))

    def _sigma(self) -> tuple[Arr, Arr, Arr]:
        n = self.x.size
        lam = self.alpha**2 * (n + self.kappa) - n
        s = np.linalg.cholesky((n + lam) * self.P)
        pts = np.vstack([self.x, self.x + s.T, self.x - s.T])
        wm = np.full(2 * n + 1, 1 / (2 * (n + lam)))
        wc = wm.copy()
        wm[0] = lam / (n + lam)
        wc[0] = wm[0] + 1 - self.alpha**2 + self.beta
        return pts, wm, wc

    def step(self, y: Arr, h: Callable[[Arr], Arr]) -> Arr:
        # Predict (random walk): x unchanged, P grows by Q
        self.P = self.P + self.Q
        pts, wm, wc = self._sigma()
        pts = np.clip(pts, self.lower, self.upper)
        ys = np.array([h(p) for p in pts])
        y_hat = wm @ ys
        dy = ys - y_hat
        dx = pts - self.x
        s = (wc[:, None] * dy).T @ dy + self.R
        cxy = (wc[:, None] * dx).T @ dy
        k = cxy @ np.linalg.inv(s)
        innov = y - y_hat
        self.x = np.clip(self.x + k @ innov, self.lower, self.upper)
        self.P = self.P - k @ s @ k.T
        self.P = 0.5 * (self.P + self.P.T) + 1e-12 * np.eye(self.x.size)
        return np.asarray(innov, dtype=np.float64)

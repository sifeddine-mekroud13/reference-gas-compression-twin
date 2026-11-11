"""Soft sensor: estimate discharge temperature TT-2005 from other measurements.

Use case: sensor validation. If TT-2005 drifts, the residual between measurement and the
soft-sensor estimate grows while the inputs stay healthy. Model: ridge regression on
standardised inputs (deliberately simple and auditable; physics would say T2 follows from
pressure ratio and polytropic efficiency, which the inputs carry implicitly).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from .data import FEATURES

TARGET = "100-TT-2005"
INPUTS = ["100-PT-2002", "100-TT-2003", "100-PT-2004", "100-FY-2001", "100-ST-2020", "100-JT-2102"]


@dataclass
class SoftSensor:
    model: Pipeline
    resid_sd: float

    @classmethod
    def fit(cls, x: np.ndarray) -> SoftSensor:
        xi, y = _split(x)
        model = make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13))).fit(xi, y)
        return cls(model, float(np.std(y - model.predict(xi))))

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict(_split(x)[0]))

    def residual(self, x: np.ndarray) -> np.ndarray:
        return _split(x)[1] - self.predict(x)


def _split(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    idx = [FEATURES.index(t) for t in INPUTS]
    return x[:, idx], x[:, FEATURES.index(TARGET)]

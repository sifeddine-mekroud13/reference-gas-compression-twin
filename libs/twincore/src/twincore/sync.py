"""Twin synchronization: UKF on steady-state windows using the TwinModel."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from twincore.model import K0, Operating, TwinModel
from twincore.ukf import UKF


def operating_from(v: dict[str, float]) -> Operating:
    fans = sum(1 for c in "ABCD" if v.get(f"100-IT-3010{c}", 0.0) > 10.0)
    return Operating(
        m=v["100-FY-2001"],
        n_rpm=v["100-ST-2020"],
        p1=v["100-PT-2002"] * 1e5,
        t1=v["100-TT-2003"] + K0,
        t_amb=v["100-TT-3003"] + K0,
        fans=fans,
    )


def measured_y(v: dict[str, float]) -> np.ndarray:
    return np.array(
        [
            v["100-PT-2004"] / v["100-PT-2002"],
            v["100-TT-2005"] + K0,
            v["100-JT-2102"] * 1e6 * 0.97,
            v["100-TT-3001"] + K0,
        ]
    )


@dataclass
class Synchronizer:
    model: TwinModel
    ukf: UKF = field(init=False)

    def __post_init__(self) -> None:
        self.ukf = UKF(
            x=np.array([1.0, 1.0, 1.0]),
            P=np.diag([0.02**2, 0.02**2, 0.05**2]),
            Q=np.diag([0.002**2, 0.002**2, 0.005**2]),
            R=np.diag([0.004**2, 0.6**2, 60e3**2, 0.8**2]),
        )

    def update(self, v: dict[str, float]) -> dict[str, float]:
        op = operating_from(v)

        def h(x: np.ndarray) -> np.ndarray:
            pr = self.model.predict(op, float(x[0]), float(x[1]), float(x[2]))
            return np.array([pr.pr, pr.t2, pr.power, pr.tc])

        innov = self.ukf.step(measured_y(v), h)
        x, sd = self.ukf.x, np.sqrt(np.diag(self.ukf.P))
        return {
            "f_head": float(x[0]),
            "f_eta": float(x[1]),
            "f_ua": float(x[2]),
            "sd_head": float(sd[0]),
            "sd_eta": float(sd[1]),
            "sd_ua": float(sd[2]),
            "innov_t2": float(innov[1]),
        }

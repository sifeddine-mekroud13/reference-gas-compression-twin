"""Quasi-steady twin model of Unit 100 (the "digital" side), deliberately NOT identical to the plant.

The plant simulator is the stand-in for the physical asset. To avoid the "inverse crime"
(estimating with the model that generated the data), the twin uses its own map parameters,
perturbed from the plant's by amounts typical of vendor-map versus as-built differences
(head about 1.5 percent, efficiency curve shape, cooler UA). See ADR 0009.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from plant.compressor_map import CompressorMap
from plant.params import PlantParams

K0 = 273.15


@dataclass(frozen=True)
class Mismatch:
    head: float = 0.985
    eta: float = 1.01
    eta_curvature: float = 0.95
    psi_peak: float = 1.09
    ua: float = 0.93


@dataclass(frozen=True)
class Operating:
    m: float  # kg/s compressor flow
    n_rpm: float
    p1: float  # Pa
    t1: float  # K
    t_amb: float  # K
    fans: int


@dataclass(frozen=True)
class Prediction:
    pr: float
    t2: float  # K
    power: float  # W
    tc: float  # K
    surge_margin: float  # %
    head: float
    eta: float


class TwinModel:
    def __init__(self, plant_params: PlantParams, mismatch: Mismatch | None = None) -> None:
        mm = mismatch or Mismatch()
        self.p = copy.deepcopy(plant_params)
        self.map = CompressorMap(
            head_design=plant_params.head_design * mm.head,
            q_design=plant_params.q_design,
            eta_design=plant_params.eta_design * mm.eta,
            sigma_design=plant_params.sigma_design,
            temp_exp_design=plant_params.temp_exponent_design,
            phi_surge=plant_params.phi_surge,
            psi_peak=mm.psi_peak,
            eta_curvature=plant_params.eta_curvature * mm.eta_curvature,
        )
        self.ua = plant_params.ua_design * mm.ua

    def predict(self, op: Operating, f_head: float, f_eta: float, f_ua: float) -> Prediction:
        p = self.p
        zrt = p.z1 * p.r_gas * op.t1
        rho1 = op.p1 / zrt
        q = op.m / rho1
        s = op.n_rpm / p.n_design_rpm
        head = self.map.head(q, s, f_head)
        eta = self.map.efficiency(q, s, f_eta)
        pr = self.map.pressure_ratio(head, eta, zrt)
        t2 = op.t1 * self.map.temperature_ratio(pr, eta)
        air = p.air_flow_design * op.fans / p.n_fans + 0.08 * p.air_flow_design
        ua = self.ua * f_ua * (air / p.air_flow_design) ** 0.6
        c_gas, c_air = max(op.m, 0.5) * p.cp_gas, air * 1007.0
        c_min, c_max = min(c_gas, c_air), max(c_gas, c_air)
        ntu, cr = ua / c_min, c_min / c_max
        eps = 1 - math.exp((ntu**0.22 / cr) * (math.exp(-cr * ntu**0.78) - 1))
        tc = t2 - eps * c_min * (t2 - op.t_amb) / c_gas
        q_s = self.map.surge_flow(s, zrt)
        return Prediction(pr, t2, op.m * head / eta, tc, (q / q_s - 1) * 100, head, eta)

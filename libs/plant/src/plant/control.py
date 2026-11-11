"""Emulated control layer: PID loops, anti-surge controller, fan staging, machine protection.

Control philosophy: docs/control-philosophy.md. Scan rates: anti-surge and speed 20 Hz
(dedicated compressor controllers typically scan at 20 to 40 ms), other loops 10 Hz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from plant.compressor_map import invariant_hr
from plant.model import Plant


@dataclass
class PID:
    """Positional PI(D) with clamping anti-windup. direct=True: output rises when PV > SP."""

    kp: float
    ti: float  # s, integral time
    out_min: float
    out_max: float
    direct: bool = True
    td: float = 0.0
    sp: float = 0.0
    out: float = 0.0
    auto: bool = True
    _i: float = 0.0
    _prev_e: float = 0.0

    def init(self, pv: float, out: float) -> None:
        """Bumpless initialization: integral term chosen so the output equals ``out``."""
        e = (pv - self.sp) if self.direct else (self.sp - pv)
        self._i = out - self.kp * e
        self.out = out
        self._prev_e = e

    def update(self, pv: float, dt: float) -> float:
        if not self.auto:
            self.init(pv, self.out)
            return self.out
        e = (pv - self.sp) if self.direct else (self.sp - pv)
        p_term = self.kp * e
        d_term = self.kp * self.td * (e - self._prev_e) / dt if self.td else 0.0
        i_new = self._i + self.kp * e * dt / self.ti
        raw = p_term + i_new + d_term
        if self.out_min <= raw <= self.out_max:
            self._i = i_new  # integrate only when not saturated
        self.out = min(self.out_max, max(self.out_min, p_term + self._i + d_term))
        self._prev_e = e
        return self.out


@dataclass
class SurgeLine:
    """Surge limit line in invariant coordinates: q_r^2 = dp_o / p_s versus h_r.

    Fitted at start-up from the (designer-supplied) map, as a vendor would supply the
    SLL to the anti-surge controller. Independent of gas composition in the ideal-gas limit.
    """

    slope: float
    intercept: float

    def qr2(self, hr: float) -> float:
        return self.slope * hr + self.intercept


def fit_surge_line(plant: Plant) -> SurgeLine:
    p = plant.p
    hrs, qs = [], []
    c = p.m_design / math.sqrt(25e3 * p.rho1_design)
    zrt = p.z1 * p.r_gas * p.t1_design
    for s in np.linspace(0.65, 1.1, 10):
        q_s = plant.map.surge_flow(float(s), zrt)
        m_s = q_s * p.rho1_design
        head = plant.map.head(q_s, float(s))
        eta = plant.map.efficiency(q_s, float(s))
        pr = plant.map.pressure_ratio(head, eta, zrt)
        hrs.append(invariant_hr(pr, p.sigma_design))
        qs.append(m_s**2 / (c**2 * p.rho1_design) / p.p1_design)
    slope, intercept = np.polyfit(hrs, qs, 1)
    return SurgeLine(float(slope), float(intercept))


def surge_margin(dp_o: float, p_s: float, p_d: float, line: SurgeLine, sigma: float) -> float:
    """Flow-based surge margin in percent: (Q / Q_surge - 1) * 100 at the current reduced head."""
    hr = invariant_hr(p_d / p_s, sigma)
    qr2_s = max(line.qr2(hr), 1e-9)
    return (math.sqrt(max(dp_o / p_s, 0.0) / qr2_s) - 1) * 100


@dataclass
class AntiSurge:
    line: SurgeLine
    sigma: float
    scl_margin: float = 15.0  # surge control line, % margin (flat PR curve near peak, see control philosophy)
    rapid_margin: float = 8.0  # recycle trip line: open-loop step
    pid: PID = field(default_factory=lambda: PID(kp=4.0, ti=5.0, out_min=0, out_max=100, direct=False))
    sm: float = 50.0
    output: float = 0.0

    def __post_init__(self) -> None:
        self.pid.sp = self.scl_margin

    def update(self, dp_o: float, p_s: float, p_d: float, dt: float, tripped: bool) -> float:
        self.sm = surge_margin(dp_o, p_s, p_d, self.line, self.sigma)
        if tripped:
            self.pid.init(self.sm, 100.0)
            self.output = 100.0
            return self.output
        out = self.pid.update(self.sm, dt)
        if self.sm < self.rapid_margin and out < self.output + 30:
            out = min(100.0, max(out, self.output + 30))
            self.pid.init(self.sm, out)
        self.output = out
        return out


@dataclass
class FanStaging:
    """Discrete fan staging with deadband and minimum time between steps."""

    sp: float
    n_max: int
    band: float = 2.0
    min_interval_s: float = 60.0
    n_on: int = 4
    _timer: float = 0.0

    def update(self, t: float, dt: float) -> int:
        self._timer += dt
        if self._timer >= self.min_interval_s:
            if t > self.sp + self.band and self.n_on < self.n_max:
                self.n_on += 1
                self._timer = 0.0
            elif t < self.sp - self.band and self.n_on > 0:
                self.n_on -= 1
                self._timer = 0.0
        return self.n_on


TRIP_LIMITS = {  # tag -> (limit, direction); mirrors alarms.yaml entries with trip: true
    "100-LT-1104": (1.1, 1),
    "100-TT-2005": (155.0, 1),
    "100-VT-2010X": (75.0, 1),
    "100-VT-2011X": (75.0, 1),
    "100-TT-2013": (115.0, 1),
}


@dataclass
class ControlSystem:
    plant: Plant
    advisory_requests: dict[str, float] = field(default_factory=dict)
    tripped: bool = False
    trip_cause: str = ""

    def __post_init__(self) -> None:
        p = self.plant.p
        self.tau_max = p.motor_rated_w / (p.n_max_rpm * 2 * math.pi / 60) * 1.05
        self.sic = PID(kp=3000.0 / 100, ti=2.0, out_min=0.0, out_max=self.tau_max, direct=False)
        self.sic.sp = p.n_design_rpm
        self.pic = PID(kp=400.0, ti=20.0, out_min=p.n_min_rpm, out_max=p.n_max_rpm, direct=True)
        self.pic.sp = p.p1_design / 1e5
        self.lic = PID(kp=150.0, ti=120.0, out_min=0, out_max=100, direct=True)
        self.lic.sp = 0.6
        self.fans = FanStaging(sp=p.tc_setpoint - 273.15, n_max=p.n_fans)
        self.asc = AntiSurge(fit_surge_line(self.plant), p.sigma_design)
        x = self.plant.x
        self.sic.init(
            p.n_design_rpm,
            self.plant.tau_comp or p.m_design * p.head_design / p.eta_design / x.omega,
        )
        self.pic.init(x.p1 / 1e5, p.n_design_rpm)
        self.lic.init(x.level, 1.0)
        self.asc.pid.init(50.0, 0.0)
        self.plant.u.torque_cmd = self.sic.out

    def trip(self, cause: str) -> None:
        if not self.tripped:
            self.tripped, self.trip_cause = True, cause

    def reset_trip(self) -> None:
        self.tripped, self.trip_cause = False, ""

    def fast(self, meas: dict[str, float], dt: float) -> None:
        """20 Hz: speed loop and anti-surge."""
        u = self.plant.u
        rpm = meas["100-ST-2020"]
        if self.tripped:
            u.torque_cmd = 0.0
            self.sic.init(rpm, 0.0)
        else:
            self.sic.sp = self.pic.out
            u.torque_cmd = self.sic.update(rpm, dt)
        out = self.asc.update(
            meas["100-FT-2001"] * 1e3,
            meas["100-PT-2002"] * 1e5,
            meas["100-PT-2004"] * 1e5,
            dt,
            self.tripped,
        )
        u.asv_cmd = out / 100

    def slow(self, meas: dict[str, float], dt: float) -> None:
        """10 Hz: suction pressure, level, fan staging, machine protection."""
        u = self.plant.u
        if not self.tripped:
            self.pic.update(meas["100-PT-2002"], dt)
        u.lv_cmd = self.lic.update(meas["100-LT-1103"], dt) / 100
        u.fans_cmd = self.fans.update(meas["100-TT-3001"], dt)
        for tag, (lim, sign) in TRIP_LIMITS.items():
            if tag in meas and sign * (meas[tag] - lim) > 0:
                self.trip(f"{tag} beyond trip limit {lim}")

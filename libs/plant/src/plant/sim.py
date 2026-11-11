"""Simulation runtime: multi-rate loop tying plant, sensors, control and alarms together.

Rates: plant fast states 500 Hz (dt 2 ms), anti-surge and speed control 20 Hz, other
control and slow plant states 10 Hz, alarms 1 Hz, real-gas property refresh every 10 s.
``advance(seconds)`` runs as fast as the CPU allows (faster than real time); a real-time
driver simply calls it with wall-clock deltas.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from engdata.dataset import Dataset, load
from plant.alarms import AlarmEngine
from plant.control import ControlSystem
from plant.model import Degradation, Plant
from plant.params import PlantParams, from_dataset
from plant.sensors import GOOD, Sensor, SensorFault, build_sensors
from thermo_ref import GasMixture

FAST_TAGS = ("100-FT-2001", "100-PT-2002", "100-PT-2004", "100-ST-2020")
K0 = 273.15


@dataclass
class Rates:
    """Continuous degradation rates (per hour of simulated time)."""

    head_per_h: float = 0.0
    eff_per_h: float = 0.0
    ua_per_h: float = 0.0
    bearing_per_h: float = 0.0


@dataclass
class Simulation:
    params: PlantParams | None = None
    dataset: Dataset | None = None
    seed: int = 0
    dt: float = 0.002
    ambient_mean_c: float = 42.0
    ambient_amp_c: float = 8.0
    t0_hour: float = 12.0
    rates: Rates = field(default_factory=Rates)
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.dataset = self.dataset or load()
        self.params = self.params or from_dataset(self.dataset)
        self.params = copy.deepcopy(self.params)  # scenarios must never mutate shared params
        self.plant = Plant(self.params, Degradation())
        self.ctrl = ControlSystem(self.plant)
        self.sensors: dict[str, Sensor] = build_sensors(self.dataset.tags)
        self.alarms = AlarmEngine.from_dataset(self.dataset.alarms)
        self.gas = GasMixture(self.dataset.bod["feed_gas"]["composition"])
        self.rng = np.random.default_rng(self.seed)
        self.values: dict[str, float] = {}
        self.quality: dict[str, str] = {}
        self._step = 0
        self._slug_until = 0.0
        self._slug_rate = 0.0
        self.events = sorted(self.events, key=lambda e: e["t"])
        self._refresh_properties()
        self._sample(list(self.sensors), 0.1)

    @property
    def t(self) -> float:
        return self.plant.x.time

    # ---- scenario events ---------------------------------------------------
    @classmethod
    def from_scenario(cls, path: Path, **kw: Any) -> Simulation:
        sc = yaml.safe_load(path.read_text())
        rates = Rates(**sc.get("rates", {}))
        return cls(rates=rates, events=sc.get("events", []), seed=sc.get("seed", 0), **kw)

    def apply_event(self, e: dict[str, Any]) -> None:
        d, u = self.plant.deg, self.plant.u
        a = e["action"]
        if a == "sensor_fault":
            f = self.sensors[e["tag"]].fault
            for k in ("drift_per_s", "bias", "stuck", "bad", "dropout_prob", "noise_mult"):
                if k in e:
                    setattr(f, k, e[k])
        elif a == "sensor_clear":
            self.sensors[e["tag"]].fault = SensorFault()
        elif a == "fan_fail":
            d.fans_failed.add(int(e["fan"]))
        elif a == "fan_repair":
            d.fans_failed.discard(int(e["fan"]))
        elif a == "lv_stuck":
            d.lv_stuck = e.get("position")
        elif a == "slug":
            self._slug_rate = e["volume_m3"] / e["duration_s"]
            self._slug_until = self.t + e["duration_s"]
        elif a == "feed_pressure":
            u.p_header_in = e["value_bara"] * 1e5
        elif a == "export_pressure":
            u.p_header_out = e["value_bara"] * 1e5
        elif a == "trip":
            self.ctrl.trip("manual trip (scenario)")
        elif a == "reset_trip":
            self.ctrl.reset_trip()
        elif a == "degradation":
            for k in ("head_factor", "eff_factor", "ua_factor", "bearing_wear_de"):
                if k in e:
                    setattr(d, k, e[k])
        elif a == "rates":
            for k, v in e.items():
                if k not in ("t", "action"):
                    setattr(self.rates, k, v)
        elif a == "wash":  # offline/online wash recovers most of the head/efficiency loss
            rec = e.get("recovery", 0.8)
            d.head_factor += (1 - d.head_factor) * rec
            d.eff_factor += (1 - d.eff_factor) * rec
        elif a == "setpoint":
            {"100-PIC-2002": self.ctrl.pic, "100-LIC-1103": self.ctrl.lic}[e["tag"]].sp = e["value"]
        else:
            raise ValueError(f"unknown scenario action {a}")

    # ---- main loop ---------------------------------------------------------
    def ambient_k(self) -> float:
        hour = (self.t0_hour + self.t / 3600) % 24
        return K0 + self.ambient_mean_c + self.ambient_amp_c * math.sin(2 * math.pi * (hour - 9) / 24)

    def advance(self, seconds: float) -> None:
        n = round(seconds / self.dt)
        for _ in range(n):
            self._tick()

    def _tick(self) -> None:
        pl, dt = self.plant, self.dt
        while self.events and self.events[0]["t"] <= self.t:
            self.apply_event(self.events.pop(0))
        pl.step_fast(dt)
        self._step += 1
        k = self._step
        if k % 25 == 0:  # 20 Hz
            self._sample(FAST_TAGS, 0.05)
            self.ctrl.fast(self.values, 0.05)
        if k % 50 == 0:  # 10 Hz
            pl.u.t_ambient = self.ambient_k()
            pl.u.liquid_extra_m3_s = self._slug_rate if self.t < self._slug_until else 0.0
            pl.step_slow(0.1)
            self._sample([s for s in self.sensors if s not in FAST_TAGS], 0.1)
            self.ctrl.slow(self.values, 0.1)
            self._degrade(0.1)
        if k % 500 == 0:  # 1 Hz
            self._derived()
            self.alarms.update(self.values, self.quality, self.t, 1.0)
        if k % 5000 == 0:  # 0.1 Hz
            self._refresh_properties()

    def _degrade(self, dt: float) -> None:
        d, r, h = self.plant.deg, self.rates, dt / 3600
        d.head_factor = max(0.80, d.head_factor - r.head_per_h * h)
        d.eff_factor = max(0.80, d.eff_factor - r.eff_per_h * h)
        d.ua_factor = max(0.50, d.ua_factor - r.ua_per_h * h)
        d.bearing_wear_de = min(1.0, d.bearing_wear_de + r.bearing_per_h * h)

    def _refresh_properties(self) -> None:
        pl, x = self.plant, self.plant.x
        try:
            s1 = self.gas.state_pt(x.p1, x.t1)
            s2 = self.gas.state_pt(x.p2, max(x.t2, x.tc))
            s2c = self.gas.state_pt(x.p2, x.tc)
        except Exception:  # keep last values outside the property model's convergence range
            return
        pl.z1 = s1.z
        pl.a1_sq, pl.a2_sq, pl.rho2c = s1.a**2, s2.a**2, s2c.rho

    # ---- instruments -------------------------------------------------------
    def truth(self) -> dict[str, float]:
        pl, x, p = self.plant, self.plant.x, self.plant.p
        frac = max(x.m_c / p.m_design, 0.0)
        de, nde = pl.vibration()
        fans_on = [i < pl.u.fans_cmd and i not in pl.deg.fans_failed for i in range(p.n_fans)]
        current = pl.power / 0.97 / (math.sqrt(3) * 11e3 * 0.9)
        return {
            "100-PT-1101": (x.p1 + 0.5e5 * frac**2) / 1e5,
            "100-TT-1102": x.t1 - K0,
            "100-LT-1103": x.level,
            "100-LT-1104": x.level,
            "100-PDT-1105": 0.4 * frac**2 * (1 + 2 * max(x.level - 0.9, 0)),
            "100-FT-2001": pl.fe_dp() / 1e3,
            "100-PT-2002": x.p1 / 1e5,
            "100-TT-2003": x.t1 - K0,
            "100-PT-2004": x.p2 / 1e5,
            "100-TT-2005": x.t2 - K0,
            "100-VT-2010X": de,
            "100-VT-2010Y": 0.9 * de,
            "100-VT-2011X": nde,
            "100-VT-2011Y": 0.9 * nde,
            "100-ZT-2012": 0.05 + 0.1 * (pl.pr - 2.62) / 2.62,
            "100-TT-2013": x.t_bearing_de - K0,
            "100-TT-2014": x.t_bearing_nde - K0,
            "100-TT-2015": x.t_thrust - K0,
            "100-ST-2020": x.omega * 60 / (2 * math.pi),
            "100-ZT-2031": x.asv * 100,
            "100-JT-2102": pl.power / 0.97 / 1e6,
            "100-IT-2103": current,
            "100-TT-2104": x.t_winding - K0,
            "100-TT-3001": x.tc - K0,
            "100-PT-3002": (x.p2 - 1e5 * frac**2) / 1e5,
            "100-TT-3003": pl.u.t_ambient - K0,
            **{f"100-IT-3010{c}": (70.0 if fans_on[i] else 0.0) for i, c in enumerate("ABCD")},
            "100-FT-4001": pl.m_out,
            "100-AT-4002": 96.52,
            "100-AT-4003": self.gas.molar_mass * 1e3,
            "100-PT-4004": (pl.u.p_header_out or p.p_header_out) / 1e5,
        }

    def _sample(self, tags: list[str] | tuple[str, ...], dt: float) -> None:
        tr = self.truth()
        for tag in tags:
            v, q = self.sensors[tag].sample(tr[tag], dt, self.rng)
            self.values[tag], self.quality[tag] = v, q

    def _derived(self) -> None:
        """DCS-side derived values: controller faceplates, compensated flow, surge margin."""
        c, v, q = self.ctrl, self.values, self.quality
        for name, pid in (
            ("100-PIC-2002", c.pic),
            ("100-LIC-1103", c.lic),
            ("100-SIC-2101", c.sic),
        ):
            v[f"{name}.SP"], v[f"{name}.OUT"] = pid.sp, pid.out
        v["100-TIC-3001.SP"], v["100-TIC-3001.OUT"] = c.fans.sp, float(c.fans.n_on)
        v["100-UIC-2030.SP"], v["100-UIC-2030.OUT"] = c.asc.scl_margin, c.asc.output
        v["100-LV-1103"], v["100-FV-2030"] = c.lic.out, c.asc.output
        v["100-UY-2042"] = c.asc.sm
        p = self.plant.p
        rho1 = v["100-PT-2002"] * 1e5 / (self.plant.z1 * p.r_gas * (v["100-TT-2003"] + K0))
        cfe = p.m_design / math.sqrt(25e3 * p.rho1_design)
        v["100-FY-2001"] = cfe * math.sqrt(max(v["100-FT-2001"], 0) * 1e3 * rho1)
        bad = any(not q[t].startswith("Good") for t in FAST_TAGS)
        for tag in ("100-UY-2042", "100-FY-2001"):
            q[tag] = "UncertainSubNormal" if bad else GOOD
        v["TRIP"] = 1.0 if c.tripped else 0.0

    def snapshot(self) -> dict[str, tuple[float, str]]:
        return {k: (val, self.quality.get(k.split(".")[0], GOOD)) for k, val in self.values.items()}

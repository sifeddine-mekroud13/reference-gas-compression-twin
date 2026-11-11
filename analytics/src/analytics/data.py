"""Labelled datasets from the plant simulator (measured, noisy values, 10 s sampling).

Each fault run starts healthy and injects one fault at t_fault. Degradation rates are
time-compressed so a run lasts about an hour of simulated time.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

import numpy as np

from plant.sim import Rates, Simulation

FEATURES = [
    "100-PT-2002",
    "100-TT-2003",
    "100-PT-2004",
    "100-TT-2005",
    "100-FY-2001",
    "100-ST-2020",
    "100-JT-2102",
    "100-TT-3001",
    "100-TT-3003",
    "100-VT-2010X",
    "100-VT-2011X",
    "100-TT-2013",
    "100-TT-2014",
    "100-TT-2015",
    "100-ZT-2031",
    "100-LT-1103",
    "100-PT-1101",
    "100-TT-2104",
]

FAULTS: dict[str, dict[str, Any]] = {
    "normal": {},
    "fouling": {"rates": {"head_per_h": 0.04, "eff_per_h": 0.05}},
    "bearing_wear": {"rates": {"bearing_per_h": 0.6}},
    "fan_failure": {"events": [{"action": "fan_fail", "fan": 0}, {"action": "fan_fail", "fan": 1}]},
    "tt2005_drift": {"events": [{"action": "sensor_fault", "tag": "100-TT-2005", "drift_per_s": 0.002}]},
    "pt2004_stuck": {"events": [{"action": "sensor_fault", "tag": "100-PT-2004", "stuck": True}]},
}


@dataclass
class Run:
    name: str
    t: np.ndarray
    x: np.ndarray
    label: np.ndarray  # 1 after fault onset


def simulate(name: str, hours: float = 1.0, t_fault: float = 1200.0, seed: int = 0, warmup: float = 120.0) -> Run:
    spec = FAULTS[name]
    sim = Simulation(seed=seed, ambient_amp_c=3.0)
    sim.advance(warmup)
    ts, xs = [], []
    applied = False
    n = int(hours * 3600 / 10)
    for k in range(n):
        t = k * 10.0
        if not applied and t >= t_fault and name != "normal":
            for e in spec.get("events", []):
                sim.apply_event({"t": 0, **e})
            if "rates" in spec:
                sim.rates = Rates(**spec["rates"])
            applied = True
        sim.advance(10.0)
        ts.append(t)
        xs.append([sim.values[f] for f in FEATURES])
    t_arr = np.array(ts)
    lab = (t_arr >= t_fault).astype(int) if name != "normal" else np.zeros(n, dtype=int)
    return Run(name, t_arr, np.array(xs), lab)


def _job(args: tuple[str, float, float, int]) -> Run:
    return simulate(*args)


def dataset(hours: float = 1.0, seeds: int = 1) -> list[Run]:
    jobs = [("normal", 2.0 * hours, 1e9, s) for s in range(seeds)]
    jobs += [(f, hours, 1200.0, 100 + s) for f in FAULTS if f != "normal" for s in range(seeds)]
    with ProcessPoolExecutor() as ex:
        return list(ex.map(_job, jobs))

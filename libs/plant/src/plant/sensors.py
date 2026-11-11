"""Sensor model: makes the data realistically dirty.

Per instrument: Gaussian noise, ADC quantization (16 bit over the range), first-order lag,
and injectable faults: drift, stuck value, bias, bad (NE 43 failure current, reported as
BadSensorFailure), dropouts (UncertainLastUsableValue), and over-range clamping
(UncertainEngineeringUnitsExceeded, NE 43 saturation at 3.8 / 20.5 mA).
Quality names follow OPC UA StatusCode symbolic names (IEC 62541-4/6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

GOOD = "Good"
UNCERTAIN_LUV = "UncertainLastUsableValue"
UNCERTAIN_EU = "UncertainEngineeringUnitsExceeded"
BAD_SENSOR = "BadSensorFailure"


@dataclass
class SensorFault:
    drift_per_s: float = 0.0  # engineering units per second
    bias: float = 0.0
    stuck: bool = False
    bad: bool = False
    dropout_prob: float = 0.0
    noise_mult: float = 1.0


@dataclass
class Sensor:
    tag: str
    lo: float
    hi: float
    noise_frac: float = 0.001  # 1-sigma noise as fraction of span
    tau: float = 0.5
    fault: SensorFault = field(default_factory=SensorFault)
    value: float = float("nan")
    quality: str = GOOD
    _filtered: float | None = None
    _drift: float = 0.0

    def sample(self, truth: float, dt: float, rng: np.random.Generator) -> tuple[float, str]:
        span = self.hi - self.lo
        f = self.fault
        if self._filtered is None:
            self._filtered = truth
        self._filtered += (truth - self._filtered) * min(1.0, dt / max(self.tau, 1e-6))
        self._drift += f.drift_per_s * dt
        if f.bad:
            self.quality = BAD_SENSOR
            return self.value, self.quality
        if f.stuck and not np.isnan(self.value):
            self.quality = GOOD  # a stuck transmitter reports Good: the analytics must catch it
            return self.value, self.quality
        if f.dropout_prob and rng.random() < f.dropout_prob:
            self.quality = UNCERTAIN_LUV
            return self.value, self.quality
        v = self._filtered + f.bias + self._drift
        v += rng.normal(0.0, self.noise_frac * span * f.noise_mult)
        lsb = span / 65535
        v = round(v / lsb) * lsb
        lo_sat, hi_sat = self.lo - 0.0125 * span, self.hi + 0.03125 * span  # NE 43 3.8/20.5 mA
        if v < self.lo or v > self.hi:
            self.quality = UNCERTAIN_EU
            v = min(max(v, lo_sat), hi_sat)
        else:
            self.quality = GOOD
        self.value = v
        return v, self.quality


def build_sensors(tags: list[dict[str, object]]) -> dict[str, Sensor]:
    out: dict[str, Sensor] = {}
    for t in tags:
        if t["class"] != "instrument":
            continue
        name = str(t["tag"])
        rng_lo_hi: list[float] = t["range"]  # type: ignore[assignment]
        lo, hi = rng_lo_hi
        noise = 0.002 if "-VT-" in name else 0.001
        tau = 0.05 if any(k in name for k in ("-FT-2001", "-PT-2002", "-PT-2004", "-ST-")) else 0.5
        out[name] = Sensor(name, float(lo), float(hi), noise_frac=noise, tau=tau)
    return out

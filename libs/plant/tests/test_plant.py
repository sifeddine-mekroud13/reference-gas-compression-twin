"""Plant and control behaviour tests (qualitative literature behaviour, quantitative design point)."""

import numpy as np
import pytest

from plant.compressor_map import CompressorMap
from plant.control import PID
from plant.params import from_dataset
from plant.sensors import BAD_SENSOR, UNCERTAIN_EU, Sensor, SensorFault
from plant.sim import Simulation


@pytest.fixture(scope="module")
def params():  # type: ignore[no-untyped-def]
    return from_dataset()


def test_design_steady_state(params) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(params=params)
    s.advance(60)
    v = s.values
    assert v["100-PT-2002"] == pytest.approx(29.0, abs=0.2)
    assert v["100-PT-2004"] == pytest.approx(76.0, abs=0.5)
    assert v["100-ST-2020"] == pytest.approx(9000, rel=0.02)
    assert v["100-TT-2005"] == pytest.approx(133.7, abs=1.5)  # M1 multi-step result
    assert v["100-FY-2001"] == pytest.approx(33.0, rel=0.02)
    assert not s.ctrl.tripped


def test_map_passes_design_point_and_fan_laws(params) -> None:  # type: ignore[no-untyped-def]
    m = CompressorMap(
        params.head_design,
        params.q_design,
        params.eta_design,
        params.sigma_design,
        params.temp_exponent_design,
    )
    assert m.head(params.q_design, 1.0) == pytest.approx(params.head_design, rel=1e-9)
    # Fan laws: Q ~ N, H ~ N^2 at corresponding points
    assert m.head(0.9 * params.q_design, 0.9) == pytest.approx(0.81 * params.head_design, rel=1e-9)
    zrt = params.z1 * params.r_gas * params.t1_design
    pr = m.pressure_ratio(params.head_design, params.eta_design, zrt)
    assert pr == pytest.approx(params.p2_design / params.p1_design, rel=2e-3)
    # Pressure-ratio peak (surge) lies right of the head peak because eta falls off-design
    assert m.surge_flow(1.0, zrt) / params.q_design > params.phi_surge


def _reversals(s: Simulation, seconds: float) -> int:
    n, prev = 0, s.plant.x.m_c
    for _ in range(int(seconds / 0.05)):
        s.advance(0.05)
        if prev > 0 >= s.plant.x.m_c:
            n += 1
        prev = s.plant.x.m_c
    return n


def test_surge_without_antisurge(params) -> None:  # type: ignore[no-untyped-def]
    """Greitzer B about 1: raising export pressure past the surge line gives flow reversal (deep surge)."""
    s = Simulation(params=params, events=[{"t": 5, "action": "export_pressure", "value_bara": 84}])
    s.ctrl.asc.update = lambda *a, **k: 0.0  # type: ignore[method-assign]
    assert _reversals(s, 60) >= 2


def test_antisurge_prevents_surge(params) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(params=params, events=[{"t": 5, "action": "export_pressure", "value_bara": 84}])
    assert _reversals(s, 60) == 0
    assert s.ctrl.asc.sm > 5.0


def test_level_trip_on_stuck_valve(params) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(
        params=params,
        events=[
            {"t": 1, "action": "lv_stuck", "position": 0.0},
            {"t": 2, "action": "slug", "volume_m3": 3.0, "duration_s": 60},
        ],
    )
    s.advance(200)
    assert s.ctrl.tripped and "LT-1104" in s.ctrl.trip_cause


def test_fouling_raises_discharge_temperature_and_power(params) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(params=params)
    s.advance(30)
    t0, p0 = s.values["100-TT-2005"], s.values["100-JT-2102"]
    s.plant.deg.head_factor = s.plant.deg.eff_factor = 0.95
    s.advance(90)
    assert s.values["100-TT-2005"] > t0 + 3
    assert s.values["100-JT-2102"] > p0 * 1.02


def test_alarm_ack_and_shelve(params) -> None:  # type: ignore[no-untyped-def]
    s = Simulation(params=params, events=[{"t": 1, "action": "slug", "volume_m3": 1.5, "duration_s": 30}])
    s.advance(120)
    keys = {e["alarm"] for e in s.alarms.events}
    assert "100-LT-1103.H" in keys
    assert s.alarms.shelve("100-TT-3001.H", s.t, 600)


def test_pid_bumpless_and_antiwindup() -> None:
    pid = PID(kp=1.0, ti=10.0, out_min=0, out_max=100, direct=False, sp=50.0)
    pid.init(50.0, 30.0)
    assert pid.update(50.0, 0.1) == pytest.approx(30.0)
    for _ in range(10000):
        pid.update(0.0, 0.1)  # large error saturates output
    assert pid.out == 100.0
    out = pid.update(60.0, 0.1)
    assert out < 100.0  # recovers immediately: no integral windup


def test_sensor_faults() -> None:
    rng = np.random.default_rng(0)
    s = Sensor("X", 0, 100)
    v, q = s.sample(50.0, 0.1, rng)
    assert q == "Good" and v == pytest.approx(50.0, abs=1.0)
    _, q = s.sample(150.0, 10.0, rng)
    assert q == UNCERTAIN_EU
    s.fault = SensorFault(bad=True)
    assert s.sample(50.0, 0.1, rng)[1] == BAD_SENSOR
    s.fault = SensorFault(stuck=True)
    frozen = s.value
    assert s.sample(10.0, 1.0, rng) == (frozen, "Good")  # stuck reads Good: analytics must catch it

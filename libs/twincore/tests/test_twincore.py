"""Twin core tests: KPI method, UKF recovery of hidden degradation under model mismatch, what-if."""

import numpy as np
import pytest

from plant.sim import Simulation
from thermo_ref import GasMixture
from twincore.kpi import compressor_kpis, is_steady
from twincore.model import TwinModel
from twincore.sync import Synchronizer
from twincore.whatif import Scenario, optimize_suction_setpoint, steady, wash_economics


@pytest.fixture(scope="module")
def sim() -> Simulation:
    s = Simulation(seed=4)
    s.advance(60)
    return s


def test_kpi_recovers_design_efficiency(sim: Simulation) -> None:
    gas = GasMixture(sim.dataset.bod["feed_gas"]["composition"])  # type: ignore[union-attr]
    eta, head, u95 = compressor_kpis(gas, 29.0, 40.0, 76.0, 133.70)
    assert eta == pytest.approx(0.80, abs=0.003)
    assert head == pytest.approx(164.7, rel=0.005)
    # +-0.25 K on two temperatures gives roughly +-0.5 points of efficiency: the reason
    # online efficiency must be trended, not read as a single number.
    assert 0.002 < u95 < 0.02


def test_steady_state_detector() -> None:
    assert is_steady({"100-PT-2002": [29.0, 29.01, 28.99, 29.0, 29.0]})
    assert not is_steady({"100-PT-2002": [29.0, 29.5, 30.0, 30.5, 31.0]})
    rng = np.random.default_rng(0)
    noisy = list(33.0 + rng.normal(0, 0.15, 1000))  # raw spread about 1 kg/s, mean constant
    assert is_steady({"100-FY-2001": noisy})
    ramp = [x + 0.002 * i for i, x in enumerate(noisy)]  # 2 kg/s drift over the window
    assert not is_steady({"100-FY-2001": ramp})


def test_ukf_recovers_degradation_despite_mismatch(sim: Simulation) -> None:
    s = Simulation(seed=4)
    s.advance(60)
    sync = Synchronizer(TwinModel(s.params))  # type: ignore[arg-type]
    for _ in range(20):
        s.advance(5)
        est = sync.update(s.values)
    base = (est["f_head"], est["f_eta"], est["f_ua"])
    s.plant.deg.head_factor, s.plant.deg.eff_factor, s.plant.deg.ua_factor = 0.96, 0.95, 0.85
    s.advance(240)
    for _ in range(40):
        s.advance(5)
        est = sync.update(s.values)
    assert est["f_head"] / base[0] == pytest.approx(0.96, abs=0.01)
    assert est["f_eta"] / base[1] == pytest.approx(0.95, abs=0.01)
    # Cooler UA is weakly observable: fan staging steps break the quasi-steady assumption
    # (60 s thermal lag), so the estimate wanders by about +-0.15. Known gap: gate cooler
    # updates on a steady-state window that includes fan state. Head and efficiency are tight.
    assert 0.7 < est["f_ua"] / base[2] < 1.05


def test_whatif_flags_hot_fouled_case(sim: Simulation) -> None:
    tw = TwinModel(sim.params)  # type: ignore[arg-type]
    clean = steady(tw, Scenario(ambient_c=45))
    fouled = steady(tw, Scenario(ambient_c=50, f_eta=0.88, f_head=0.92, flow_factor=1.05))
    assert not clean["violations"]
    assert fouled["discharge_temp_c"] > clean["discharge_temp_c"] + 5
    assert fouled["violations"]
    opt = optimize_suction_setpoint(tw, Scenario(), [28.0, 29.0, 30.0])
    assert opt["best"]["scenario"]["p_suction_bar"] == 30.0  # lower ratio, lower energy


def test_wash_economics() -> None:
    r = wash_economics(f_eta_now=0.95, eta_loss_per_day=0.0005, power_mw=7.0, price_per_mwh=60, wash_cost=20000)
    assert 30 < r["optimal_interval_days"] < 400
    assert r["wash_now"]

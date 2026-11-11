"""Machinery calculation tests (hand-checkable references)."""

import math

import pytest

from machinery import aircooler, separator
from machinery.compressor import polytropic_multistep, schultz
from thermo_ref import GasMixture

LEAN = {"methane": 0.95, "ethane": 0.03, "propane": 0.01, "nitrogen": 0.01}


def test_multistep_matches_ideal_gas_closed_form() -> None:
    """At low pressure a gas is ideal; for constant cp the polytropic relation
    T2/T1 = PR^((k-1)/(k*eta_p)) holds. Nitrogen near 300 K has nearly constant cp."""
    g = GasMixture({"nitrogen": 1.0})
    r = polytropic_multistep(g, 1e4, 300.0, 2e4, eta_p=0.8, steps=400)
    k = r.inlet.cp / r.inlet.cv
    t2_ideal = 300.0 * 2.0 ** ((k - 1) / (k * 0.8))
    assert r.outlet.t == pytest.approx(t2_ideal, rel=2e-3)


def test_isentropic_limit() -> None:
    g = GasMixture(LEAN)
    r = polytropic_multistep(g, 30e5, 313.15, 75e5, eta_p=1.0, steps=100)
    assert r.outlet.s == pytest.approx(r.inlet.s, abs=1e-3)
    assert r.head_polytropic == pytest.approx(r.work_specific, rel=1e-9)


def test_schultz_agrees_with_multistep_at_moderate_ratio() -> None:
    """Schultz error is small for PR about 2.5 and lean gas far from the critical point
    (Huntington 1985). Tolerance 0.5 percent on head and 0.005 on efficiency."""
    g = GasMixture(LEAN)
    ref = polytropic_multistep(g, 29e5, 313.15, 76e5, eta_p=0.80, steps=200)
    sc = schultz(g, 29e5, 313.15, 76e5, ref.outlet.t)
    assert sc.head_polytropic == pytest.approx(ref.head_polytropic, rel=5e-3)
    assert sc.eta_polytropic == pytest.approx(0.80, abs=5e-3)


def test_souders_brown_hand_calc() -> None:
    # K=0.1, rho_l=700, rho_g=20 -> v = 0.1*sqrt(680/20) = 0.58310 m/s
    assert separator.souders_brown_vmax(0.1, 700, 20) == pytest.approx(0.583095, rel=1e-5)
    # D = sqrt(4*1/(pi*0.5)) = 1.59577 m
    assert separator.min_diameter(1.0, 0.5) == pytest.approx(1.595769, rel=1e-6)
    d = separator.min_diameter(1.0, separator.souders_brown_vmax(0.1, 700, 20))
    assert separator.load_factor(1.0, d, 700, 20) == pytest.approx(0.1, rel=1e-9)
    assert separator.k_derating(0.0) == 1.0
    assert separator.k_derating(4.14e6) == pytest.approx(0.85)


def test_lmtd_hand_calc() -> None:
    # dT1=50, dT2=10 -> (50-10)/ln(5) = 24.853
    assert aircooler.lmtd_counterflow(125, 60, 50, 75) == pytest.approx(24.8534, rel=1e-4)
    assert aircooler.lmtd_counterflow(100, 50, 30, 80) == pytest.approx(20.0)
    with pytest.raises(ValueError):
        aircooler.lmtd_counterflow(60, 40, 50, 70)
    assert aircooler.required_area(1e6, 500, 1.0, 20) == pytest.approx(100.0)
    assert math.isclose(aircooler.air_mass_flow(1007.0, 1.0), 1.0)

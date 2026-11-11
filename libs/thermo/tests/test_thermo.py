"""Thermo reference tests.

Reference values:
* Methane real-gas density at ISO 13443 standard conditions: 0.6797 kg/m3,
  compression factor Z = 0.9980 (ISO 6976 tables, as widely reproduced; verify).
* Nitrogen at 300 K, 0.1 MPa: 1.1233 kg/m3 (NIST Chemistry WebBook, Span et al. EOS).
"""

import math

import pytest

from thermo_ref import P_STD, T_STD, GasMixture

R = 8.314462618


def test_methane_standard_density() -> None:
    g = GasMixture({"methane": 1.0})
    st = g.state_pt(P_STD, T_STD)
    assert st.rho == pytest.approx(0.6797, rel=5e-4)
    assert st.z == pytest.approx(0.9980, abs=3e-4)


def test_nitrogen_density_nist() -> None:
    g = GasMixture({"nitrogen": 1.0})
    assert g.state_pt(1e5, 300.0).rho == pytest.approx(1.1233, rel=5e-4)


def test_ideal_gas_limit() -> None:
    g = GasMixture({"methane": 0.9, "ethane": 0.07, "nitrogen": 0.03})
    st = g.state_pt(1e3, 300.0)
    assert st.z == pytest.approx(1.0, abs=1e-4)
    assert st.rho == pytest.approx(1e3 * g.molar_mass / (R * 300.0), rel=1e-4)


def test_ph_ps_roundtrip() -> None:
    g = GasMixture({"methane": 0.95, "ethane": 0.03, "propane": 0.01, "nitrogen": 0.01})
    st = g.state_pt(50e5, 350.0)
    assert g.state_ph(50e5, st.h, t_guess=300.0).t == pytest.approx(350.0, abs=1e-5)
    assert g.state_ps(50e5, st.s, t_guess=400.0).t == pytest.approx(350.0, abs=1e-5)


def test_rejects_bad_composition() -> None:
    with pytest.raises(ValueError):
        GasMixture({"methane": 0.5})
    with pytest.raises(ValueError):
        GasMixture({"unobtainium": 1.0})


def test_standard_flow_conversion() -> None:
    g = GasMixture({"methane": 1.0})
    assert g.mass_flow_from_standard(86_400.0) == pytest.approx(g.standard_density())
    assert math.isfinite(g.r_specific)

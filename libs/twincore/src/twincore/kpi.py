"""Performance KPIs from measurements (calculation service).

* Polytropic head and efficiency: Schultz method with real-gas properties (ASME PTC 10 style),
  machinery.compressor.schultz. Uncertainty by first-order propagation (GUM) of the
  temperature and pressure transmitter uncertainties, evaluated numerically.
* Aftercooler approach (T_gas_out - T_air_in) and gas-side duty.
* Scrubber Souders-Brown load factor (operating K over design K).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from machinery import separator
from machinery.compressor import schultz
from thermo_ref import GasMixture

K0 = 273.15


@dataclass(frozen=True)
class Kpis:
    eta_p: float
    head_p_kj: float
    eta_p_u95: float  # expanded uncertainty (k=2) of eta_p, absolute
    cooler_approach_k: float
    cooler_duty_mw: float
    scrubber_load: float


# Transmitter standard uncertainties (1-sigma), typical smart transmitters (assumed, verify vs datasheets)
U_T = 0.25  # K
U_P = 0.0005  # relative


def compressor_kpis(gas: GasMixture, p1_bar: float, t1_c: float, p2_bar: float, t2_c: float) -> tuple[float, float, float]:
    """Return (eta_p, head_p in kJ/kg, U95 of eta_p)."""

    def eta(p1: float, t1: float, p2: float, t2: float) -> float:
        return schultz(gas, p1 * 1e5, t1 + K0, p2 * 1e5, t2 + K0).eta_polytropic

    r = schultz(gas, p1_bar * 1e5, t1_c + K0, p2_bar * 1e5, t2_c + K0)
    base = r.eta_polytropic
    var = 0.0
    for i, (val, u) in enumerate(((p1_bar, U_P * p1_bar), (t1_c, U_T), (p2_bar, U_P * p2_bar), (t2_c, U_T))):
        args = [p1_bar, t1_c, p2_bar, t2_c]
        args[i] = val + u
        var += (eta(*args) - base) ** 2
    return base, r.head_polytropic / 1e3, 2 * math.sqrt(var)


def all_kpis(gas: GasMixture, v: dict[str, float], k_design: float, d_scrubber: float, rho_l: float) -> Kpis:
    eta, head, u95 = compressor_kpis(gas, v["100-PT-2002"], v["100-TT-2003"], v["100-PT-2004"], v["100-TT-2005"])
    m = v["100-FY-2001"]
    h2 = gas.state_pt(v["100-PT-2004"] * 1e5, v["100-TT-2005"] + K0).h
    hc = gas.state_pt(v["100-PT-3002"] * 1e5, v["100-TT-3001"] + K0).h
    st = gas.state_pt(v["100-PT-1101"] * 1e5, v["100-TT-1102"] + K0)
    k_op = separator.load_factor(m / st.rho, d_scrubber, rho_l, st.rho)
    k_des = k_design * separator.k_derating(v["100-PT-1101"] * 1e5 - 101325)
    return Kpis(eta, head, u95, v["100-TT-3001"] - v["100-TT-3003"], m * (h2 - hc) / 1e6, k_op / k_des)


def is_steady(series: dict[str, list[float]], rel_tol: float = 0.01, segments: int = 5) -> bool:
    """Steady-state detection on segment means.

    The window is split into ``segments`` equal parts; the signal is steady when the spread of the
    segment means is within rel_tol of the mean (1 K for temperatures). Comparing means, not raw
    extremes, makes the test insensitive to measurement noise while still catching drift and
    transients: the same idea as the ratio-of-variances test of Cao and Rhinehart (1995),
    J. Process Control 5(6), in a simpler form.
    """
    for tag, xs in series.items():
        if len(xs) < segments:
            return False
        n = len(xs) // segments
        means = [sum(xs[i * n : (i + 1) * n]) / n for i in range(segments)]
        mean = sum(means) / segments
        tol = 1.0 if "-TT-" in tag else rel_tol * max(abs(mean), 1e-6)
        if max(means) - min(means) > tol:
            return False
    return True

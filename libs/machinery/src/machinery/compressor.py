"""Centrifugal compressor thermodynamic performance (real gas).

Two methods:

* ``polytropic_multistep``: integrates the polytropic path dh = v dp / eta_p in many
  small isentropic steps (each step efficiency = eta_p). Converges to the exact real-gas
  polytropic head as the step count grows. Used as the reference and for design.
  Source: Huntington, R.A. (1985) "Evaluation of polytropic calculation methods for
  turbomachinery performance", J. Eng. Gas Turbines Power 107(4); Hundseid, Bakken and
  Helde (2006/2008) multi-step method.
* ``schultz``: Schultz (1962) polytropic method with the polytropic head factor f, as
  used by ASME PTC 10 for test evaluation. Source: Schultz, J.M. (1962) "The polytropic
  analysis of centrifugal compressors", J. Eng. Power 84(1). Verify the exact PTC 10
  procedure against the official code if available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from thermo_ref import GasMixture, GasState


@dataclass(frozen=True, slots=True)
class PolytropicResult:
    inlet: GasState
    outlet: GasState
    head_polytropic: float  # J/kg
    eta_polytropic: float  # -
    work_specific: float  # J/kg, gas power per unit mass = h2 - h1
    n_polytropic: float  # volume-based polytropic exponent ln(p2/p1)/ln(v1/v2)


def polytropic_multistep(gas: GasMixture, p1: float, t1: float, p2: float, eta_p: float, steps: int = 200) -> PolytropicResult:
    """Discharge state and polytropic head for a given polytropic efficiency."""
    if not 0.0 < eta_p <= 1.0:
        raise ValueError("eta_p must be in (0, 1]")
    if p2 <= p1:
        raise ValueError("p2 must exceed p1 for compression")
    inlet = gas.state_pt(p1, t1)
    ratio = (p2 / p1) ** (1.0 / steps)
    st = inlet
    head = 0.0
    for _ in range(steps):
        p_next = st.p * ratio
        iso = gas.state_ps(p_next, st.s, t_guess=st.t)
        dh_s = iso.h - st.h
        head += dh_s
        st = gas.state_ph(p_next, st.h + dh_s / eta_p, t_guess=iso.t)
    outlet = st
    n = math.log(p2 / p1) / math.log(outlet.rho / inlet.rho)
    return PolytropicResult(
        inlet=inlet,
        outlet=outlet,
        head_polytropic=head,
        eta_polytropic=eta_p,
        work_specific=outlet.h - inlet.h,
        n_polytropic=n,
    )


def schultz(gas: GasMixture, p1: float, t1: float, p2: float, t2: float) -> PolytropicResult:
    """Polytropic head and efficiency from measured suction and discharge p, T (Schultz)."""
    inlet = gas.state_pt(p1, t1)
    outlet = gas.state_pt(p2, t2)
    iso = gas.state_ps(p2, inlet.s, t_guess=t2)
    ln_pr = math.log(p2 / p1)
    n_s = ln_pr / math.log(iso.rho / inlet.rho)
    n = ln_pr / math.log(outlet.rho / inlet.rho)
    f = (iso.h - inlet.h) / (n_s / (n_s - 1.0) * (p2 * iso.v - p1 * inlet.v))
    head = f * n / (n - 1.0) * (p2 * outlet.v - p1 * inlet.v)
    work = outlet.h - inlet.h
    return PolytropicResult(
        inlet=inlet,
        outlet=outlet,
        head_polytropic=head,
        eta_polytropic=head / work,
        work_specific=work,
        n_polytropic=n,
    )


def impeller_count(head_polytropic: float, max_head_per_impeller: float) -> int:
    """Number of impellers needed for a head, given a per-impeller head limit (J/kg)."""
    return math.ceil(head_polytropic / max_head_per_impeller)


def tip_speed(head_per_impeller: float, head_coefficient: float) -> float:
    """Impeller tip speed u2 from psi_p = H_p / u2^2 (Ludtke convention), m/s."""
    return math.sqrt(head_per_impeller / head_coefficient)

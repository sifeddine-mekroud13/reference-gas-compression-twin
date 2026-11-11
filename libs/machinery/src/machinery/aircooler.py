"""Air-cooled heat exchanger thermal rating (lumped, design level).

Q = U * A * F * LMTD with counter-current LMTD and a cross-flow correction factor F.
Sources: Incropera and DeWitt, Fundamentals of Heat and Mass Transfer (LMTD, F); API 661
for construction requirements (not thermal method); typical bare-tube U values as quoted in
the GPSA Engineering Data Book, Section 10 (verify).
"""

from __future__ import annotations

import math

CP_AIR = 1007.0  # J/(kg K), dry air near 300-350 K (Incropera Table A.4)


def lmtd_counterflow(t_hot_in: float, t_hot_out: float, t_cold_in: float, t_cold_out: float) -> float:
    dt1 = t_hot_in - t_cold_out
    dt2 = t_hot_out - t_cold_in
    if dt1 <= 0 or dt2 <= 0:
        raise ValueError("temperature cross: infeasible counter-current exchanger")
    if math.isclose(dt1, dt2, rel_tol=1e-9):
        return dt1
    return (dt1 - dt2) / math.log(dt1 / dt2)


def required_area(duty: float, u: float, f: float, lmtd: float) -> float:
    """Bare-tube area, m2."""
    return duty / (u * f * lmtd)


def air_mass_flow(duty: float, dt_air: float) -> float:
    return duty / (CP_AIR * dt_air)

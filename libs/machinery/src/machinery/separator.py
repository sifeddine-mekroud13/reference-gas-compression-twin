"""Gas scrubber sizing with the Souders-Brown correlation.

v_max = K * sqrt((rho_l - rho_g) / rho_g)

Source: Souders, M. and Brown, G.G. (1934) Ind. Eng. Chem. 26(1); K values and the
pressure derating table follow the commonly published GPSA Engineering Data Book,
Section 7, guidance for vertical separators with wire mesh demisters (K about 0.107 m/s
at low pressure). Verify K and derating against GPSA or the demister vendor.
"""

from __future__ import annotations

import math

import numpy as np

# GPSA-style K derating vs pressure for mesh pads: (gauge pressure in Pa, factor).
# Values as commonly reproduced from GPSA Section 7; flagged for verification.
_DERATE_P_PA = np.array([0.0, 2.07e6, 4.14e6, 6.21e6, 10.34e6])  # 0, 300, 600, 900, 1500 psig
_DERATE_F = np.array([1.00, 0.90, 0.85, 0.80, 0.75])


def k_derating(p_gauge: float) -> float:
    return float(np.interp(p_gauge, _DERATE_P_PA, _DERATE_F))


def souders_brown_vmax(k: float, rho_l: float, rho_g: float) -> float:
    """Maximum allowable gas superficial velocity, m/s."""
    if rho_l <= rho_g:
        raise ValueError("liquid density must exceed gas density")
    return k * math.sqrt((rho_l - rho_g) / rho_g)


def min_diameter(q_actual: float, v_max: float) -> float:
    """Minimum vessel internal diameter for actual gas flow q (m3/s), m."""
    return math.sqrt(4.0 * q_actual / (math.pi * v_max))


def load_factor(q_actual: float, diameter: float, rho_l: float, rho_g: float) -> float:
    """Operating K-value (m/s): superficial velocity / sqrt((rho_l-rho_g)/rho_g).

    Compare against the design K to obtain the scrubber load (fraction of capacity).
    """
    v = q_actual / (math.pi * diameter**2 / 4.0)
    return v / math.sqrt((rho_l - rho_g) / rho_g)

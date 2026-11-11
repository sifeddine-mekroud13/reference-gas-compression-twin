"""Real-gas thermodynamic properties for natural gas mixtures.

Backend: CoolProp HEOS mixture model. For the GERG-2008 component set CoolProp uses the
Kunz-Wagner (GERG-2008) pure-fluid equations, reducing functions and departure functions,
so results should track GERG-2008 (ISO 20765-2) closely in the single-phase gas region.
This is NOT a certified GERG-2008 implementation: see docs/adr/0007 and the cross-check
list in docs/sizing-calculations.md.

All quantities are SI: Pa, K, kg, J, m3, mol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from CoolProp import CoolProp as cpl  # noqa: N813
from CoolProp.CoolProp import AbstractState

__all__ = ["P_STD", "T_STD", "GasMixture", "GasState"]

# ISO 13443 standard reference conditions: 15 degC, 101.325 kPa.
T_STD: Final = 288.15
P_STD: Final = 101_325.0

# Mapping from engineering-dataset component names to CoolProp fluid names.
_COOLPROP_NAMES: Final = {
    "methane": "Methane",
    "nitrogen": "Nitrogen",
    "carbon_dioxide": "CarbonDioxide",
    "ethane": "Ethane",
    "propane": "Propane",
    "isobutane": "IsoButane",
    "n_butane": "n-Butane",
    "isopentane": "Isopentane",
    "n_pentane": "n-Pentane",
    "n_hexane": "n-Hexane",
    "n_heptane": "n-Heptane",
    "n_octane": "n-Octane",
    "hydrogen_sulfide": "HydrogenSulfide",
    "water": "Water",
    "hydrogen": "Hydrogen",
    "helium": "Helium",
    "oxygen": "Oxygen",
    "carbon_monoxide": "CarbonMonoxide",
    "argon": "Argon",
}


@dataclass(frozen=True, slots=True)
class GasState:
    """Thermodynamic state of a single-phase gas."""

    p: float  # Pa
    t: float  # K
    rho: float  # kg/m3
    z: float  # -
    h: float  # J/kg
    s: float  # J/(kg K)
    cp: float  # J/(kg K)
    cv: float  # J/(kg K)
    a: float  # speed of sound, m/s

    @property
    def v(self) -> float:
        """Specific volume, m3/kg."""
        return 1.0 / self.rho

    @property
    def kappa(self) -> float:
        """Ideal-gas-like heat capacity ratio cp/cv (not the isentropic exponent)."""
        return self.cp / self.cv


class GasMixture:
    """A fixed-composition natural gas evaluated in the single-phase gas region.

    The gas phase is imposed (``specify_phase``) because the feed is far from its dew
    point at all conditions in this unit. Callers must not use this for two-phase states.
    """

    def __init__(self, mole_fractions: dict[str, float]) -> None:
        total = sum(mole_fractions.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"mole fractions must sum to 1, got {total:.8f}")
        unknown = set(mole_fractions) - set(_COOLPROP_NAMES)
        if unknown:
            raise ValueError(f"unsupported components: {sorted(unknown)}")
        self.composition = dict(mole_fractions)
        names = [_COOLPROP_NAMES[c] for c in mole_fractions]
        self._as = AbstractState("HEOS", "&".join(names))
        self._as.set_mole_fractions(list(mole_fractions.values()))
        self._as.specify_phase(cpl.iphase_gas)

    @property
    def molar_mass(self) -> float:
        """kg/mol."""
        return float(self._as.molar_mass())

    @property
    def r_specific(self) -> float:
        """Specific gas constant, J/(kg K)."""
        return float(self._as.gas_constant() / self._as.molar_mass())

    def state_pt(self, p: float, t: float) -> GasState:
        a = self._as
        a.update(cpl.PT_INPUTS, p, t)
        return GasState(
            p=p,
            t=t,
            rho=a.rhomass(),
            z=a.compressibility_factor(),
            h=a.hmass(),
            s=a.smass(),
            cp=a.cpmass(),
            cv=a.cvmass(),
            a=a.speed_sound(),
        )

    def _solve_t(self, p: float, target: float, attr: str, t_guess: float) -> GasState:
        """Newton iteration on T at fixed p for h or s (PT calls are ~100x faster than PS)."""
        t = t_guess
        for _ in range(50):
            st = self.state_pt(p, t)
            val = st.h if attr == "h" else st.s
            deriv = st.cp if attr == "h" else st.cp / t  # dh/dT|p = cp, ds/dT|p = cp/T
            dt = (target - val) / deriv
            t += dt
            if abs(dt) < 1e-7:
                return self.state_pt(p, t)
        raise RuntimeError(f"T solve for {attr} did not converge at p={p}")

    def state_ph(self, p: float, h: float, t_guess: float = 330.0) -> GasState:
        return self._solve_t(p, h, "h", t_guess)

    def state_ps(self, p: float, s: float, t_guess: float = 330.0) -> GasState:
        return self._solve_t(p, s, "s", t_guess)

    def standard_density(self) -> float:
        """Density at ISO 13443 standard conditions, kg/Sm3."""
        return self.state_pt(P_STD, T_STD).rho

    def mass_flow_from_standard(self, q_std_m3_per_day: float) -> float:
        """Convert a standard volumetric flow (Sm3/d) to mass flow (kg/s)."""
        return q_std_m3_per_day * self.standard_density() / 86_400.0

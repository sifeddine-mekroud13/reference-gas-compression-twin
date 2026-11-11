"""Compressor characteristic: Moore-Greitzer cubic head curve with fan-law speed scaling.

phi = Q / (Q_design * s), s = N / N_design (fan law: Q ~ N, H ~ N^2).
psi(phi) = psi_c0 + Hc * (1 + 1.5 (phi/W - 1) - 0.5 (phi/W - 1)^3), peak at phi = 2W.
The cubic is defined for reverse flow too, which Greitzer surge cycles need. Vendor maps
stop at the surge line, so everything left of the peak is an extrapolation and a modelling
assumption. Sources: Moore and Greitzer (1986) J. Eng. Gas Turbines Power 108; Gravdahl and
Egeland (1999) Compressor Surge and Rotating Stall, Springer.

The map is SYNTHETIC: shaped to pass through the design point computed in M1, with a 10 %
head rise to surge and surge at 70 % of design flow at design speed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompressorMap:
    head_design: float  # J/kg
    q_design: float  # m3/s suction actual
    eta_design: float
    sigma_design: float  # (n-1)/n at design efficiency
    temp_exp_design: float
    phi_surge: float = 0.70
    psi_peak: float = 1.10
    eta_curvature: float = 0.8

    @property
    def _w(self) -> float:
        return self.phi_surge / 2

    @property
    def _coeffs(self) -> tuple[float, float]:
        x = 1 / self._w - 1
        shape_design = 1 + 1.5 * x - 0.5 * x**3
        hc = (self.psi_peak - 1.0) / (2 - shape_design)
        return 1.0 - hc * shape_design, hc

    phi_choke: float = 1.35
    reverse_coeff: float = 2.0

    def _cubic(self, phi: float) -> float:
        psi_c0, hc = self._coeffs
        x = phi / self._w - 1
        return psi_c0 + hc * (1 + 1.5 * x - 0.5 * x**3)

    def psi(self, phi: float) -> float:
        """Bounded characteristic: cubic between 0 and phi_choke, orifice-like parabola in
        reverse flow (Gravdahl and Egeland 1999, ch. 2), linear beyond choke."""
        if phi < 0:
            return self._cubic(0.0) + self.reverse_coeff * phi * phi
        if phi > self.phi_choke:
            h = 1e-4
            slope = (self._cubic(self.phi_choke) - self._cubic(self.phi_choke - h)) / h
            return self._cubic(self.phi_choke) + slope * (phi - self.phi_choke)
        return self._cubic(phi)

    def eta(self, phi: float) -> float:
        return self.eta_design * max(0.30, 1 - self.eta_curvature * (phi - 1) ** 2)

    def head(self, q: float, s: float, head_factor: float = 1.0) -> float:
        s = max(s, 1e-3)
        return head_factor * s * s * self.head_design * self.psi(q / (self.q_design * s))

    def efficiency(self, q: float, s: float, eff_factor: float = 1.0) -> float:
        if s <= 1e-3:
            return 0.3
        return eff_factor * self.eta(q / (self.q_design * s))

    def sigma(self, eta: float) -> float:
        """Polytropic volume exponent (n-1)/n scales as 1/eta for fixed gas (kappa)."""
        return self.sigma_design * self.eta_design / eta

    def pressure_ratio(self, head: float, eta: float, z_r_t1: float) -> float:
        sig = self.sigma(eta)
        base = 1 + head * sig / z_r_t1
        return float(max(0.8, base) ** (1 / sig))

    def temperature_ratio(self, pr: float, eta: float) -> float:
        return float(pr ** (self.temp_exp_design * self.eta_design / eta)) if pr > 1 else 1.0

    def surge_flow(self, s: float, z_r_t1: float) -> float:
        """Suction volume flow at the peak of the PRESSURE RATIO characteristic, m3/s.

        In the Greitzer model the operating point loses stability where the slope of the
        pressure-rise characteristic turns positive. Because efficiency falls off-design,
        that peak lies at higher flow than the head peak (phi_surge), so it is found
        numerically. This is the "tested" surge line a vendor would hand over.
        """
        best_phi, best_pr = self.phi_surge, 0.0
        for i in range(400):
            phi = 0.4 + i * 0.002
            q = phi * self.q_design * s
            h = self.head(q, s)
            pr = self.pressure_ratio(h, self.efficiency(q, s), z_r_t1)
            if pr > best_pr:
                best_phi, best_pr = phi, pr
        return best_phi * self.q_design * s


def head_from_pr(pr: float, sigma: float, z_r_t1: float) -> float:
    """Polytropic head from pressure ratio (ideal polytropic form, inverse of pressure_ratio)."""
    return z_r_t1 / sigma * (pr**sigma - 1) if pr > 0 else 0.0


def invariant_hr(pr: float, sigma: float) -> float:
    """Reduced head h_r = (PR^sigma - 1) / sigma (invariant coordinates)."""
    return (pr**sigma - 1) / sigma if pr > 1 else 0.0

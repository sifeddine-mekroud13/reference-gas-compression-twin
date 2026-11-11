"""Lumped dynamic model of Unit 100 (Greitzer compression system plus slow subsystems).

Fast states (integrated at dt of a few ms):
    m_c    compressor mass flow, kg/s       dm_c/dt = (A_c / L_c) (PR(m_c, N) p1 - p2)
    p1     suction plenum pressure, Pa      dp1/dt = a1^2 / V1 (m_feed + m_rec - m_c)
    p2     discharge plenum pressure, Pa    dp2/dt = a2^2 / V2 (m_c - m_rec - m_out)
    omega  shaft speed, rad/s               J domega/dt = tau_motor - tau_comp
    asv    recycle valve position, 0..1     rate-limited first order to command
Slow states (0.1 s): scrubber level, suction temperature (recycle mixing), cooler outlet
temperature (first-order thermal lag), bearing and winding temperatures.

Integration: linearly implicit Euler for m_c (stiff), explicit Euler for the rest.

Simplifications (documented in docs/control-philosophy.md):
* a^2 uses the real-gas speed of sound, refreshed from the property library at 1 Hz.
* Feed and export are battery-limit headers with quadratic line resistance; export has a
  check valve (no reverse flow).
* Reverse-flow shaft power is a fixed fraction of design-shape power (churning).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from plant.compressor_map import CompressorMap
from plant.params import PlantParams


@dataclass
class Degradation:
    """Hidden degradation states (ground truth the twin must estimate)."""

    head_factor: float = 1.0
    eff_factor: float = 1.0
    ua_factor: float = 1.0
    bearing_wear_de: float = 0.0  # 0 new, 1 end of life
    fans_failed: set[int] = field(default_factory=set)
    lv_stuck: float | None = None


@dataclass
class Inputs:
    torque_cmd: float = 0.0  # N m from VSD speed controller
    asv_cmd: float = 0.0  # 0..1
    lv_cmd: float = 0.0  # 0..1
    fans_cmd: int = 4
    t_ambient: float = 323.15
    p_header_in: float | None = None
    p_header_out: float | None = None
    liquid_extra_m3_s: float = 0.0


@dataclass
class State:
    m_c: float
    p1: float
    p2: float
    omega: float
    asv: float = 0.0
    level: float = 0.6
    t1: float = 313.15
    t2: float = 407.0
    tc: float = 333.15
    t_bearing_de: float = 358.15
    t_bearing_nde: float = 355.15
    t_thrust: float = 361.15
    t_winding: float = 373.15
    lv: float = 0.01
    time: float = 0.0


class Plant:
    def __init__(self, params: PlantParams, degradation: Degradation | None = None) -> None:
        self.p = params
        self.deg = degradation or Degradation()
        self.map = CompressorMap(
            head_design=params.head_design,
            q_design=params.q_design,
            eta_design=params.eta_design,
            sigma_design=params.sigma_design,
            temp_exp_design=params.temp_exponent_design,
            phi_surge=params.phi_surge,
            psi_peak=params.psi_peak,
            eta_curvature=params.eta_curvature,
        )
        self.u = Inputs(t_ambient=params.t_ambient_design)
        self.x = State(
            m_c=params.m_design,
            p1=params.p1_design,
            p2=params.p2_design,
            omega=params.omega_design,
            t1=params.t1_design,
            t2=params.t2_design,
            tc=params.tc_setpoint,
        )
        self.a1_sq = 400.0**2
        self.a2_sq = 430.0**2
        self.rho2c = 52.0
        self.z1 = params.z1
        # Diagnostics, updated every fast step
        self.m_feed = params.m_design
        self.m_out = params.m_design
        self.m_rec = 0.0
        self.head = params.head_design
        self.eta = params.eta_design
        self.pr = params.p2_design / params.p1_design
        self.power = 0.0
        self.tau_comp = 0.0

    # ---- algebraic helpers -------------------------------------------------
    def rho1(self) -> float:
        return self.x.p1 / (self.z1 * self.p.r_gas * self.x.t1)

    def speed_ratio(self) -> float:
        return self.x.omega / self.p.omega_design

    def compressor(self, m_c: float, p1: float, omega: float) -> tuple[float, float, float, float]:
        """Return (head, eta, pr, shaft_power) at the given flow and speed."""
        s = omega / self.p.omega_design
        rho1 = p1 / (self.z1 * self.p.r_gas * self.x.t1)
        q = m_c / rho1
        head = self.map.head(q, s, self.deg.head_factor)
        eta = self.map.efficiency(max(q, 0.0), s, self.deg.eff_factor)
        pr = self.map.pressure_ratio(head, eta, self.z1 * self.p.r_gas * self.x.t1)
        churn = 0.02 * s**3 * self.p.m_design * self.p.head_design  # windage, always > 0
        if m_c > 0:
            power = m_c * max(head, 0.0) / eta + churn
        else:
            power = 0.3 * abs(m_c) * s * s * self.p.head_design + churn
        return head, eta, pr, power

    # ---- fast dynamics -----------------------------------------------------
    def step_fast(self, dt: float) -> None:
        x, p, u = self.x, self.p, self.u
        head, eta, pr, power = self.compressor(x.m_c, x.p1, x.omega)
        p_in = u.p_header_in if u.p_header_in is not None else p.p_header_in
        dp_feed = p_in - x.p1
        m_feed = math.copysign(p.k_feed * math.sqrt(abs(dp_feed)), dp_feed)
        p_exp = u.p_header_out if u.p_header_out is not None else p.p_header_out
        dp_out = x.p2 - p_exp
        m_out = p.k_export * math.sqrt(dp_out) if dp_out > 0 else 0.0  # check valve
        dp_rec = max(x.p2 - x.p1, 0.0)
        m_rec = x.asv * p.k_recycle * math.sqrt(self.rho2c * dp_rec)

        omega = max(x.omega, 1.0)
        tau_comp = power / omega
        dm = p.a_c / p.l_c * (pr * x.p1 - x.p2)
        dp1 = self.a1_sq / p.v_suction * (m_feed + m_rec - x.m_c)
        dp2 = self.a2_sq / p.v_discharge * (x.m_c - m_rec - m_out)
        dw = (u.torque_cmd - tau_comp) / p.inertia
        # ASV: rate limit (full stroke in asv_stroke_s) towards command
        rate = 1.0 / p.asv_stroke_s
        d_asv = max(-rate, min(rate, (u.asv_cmd - x.asv) / 0.2))

        # Linearly implicit (Rosenbrock-Euler) update for the stiff duct equation: the
        # compressor characteristic slope gives eigenvalues near -4000 1/s, so explicit Euler
        # at 2 ms is unstable. Jacobian by one-sided finite difference.
        eps = 1e-3 * max(abs(x.m_c), 1.0)
        pr_eps = self.compressor(x.m_c + eps, x.p1, x.omega)[2]
        dfdm = p.a_c / p.l_c * x.p1 * (pr_eps - pr) / eps
        x.m_c += dm * dt / (1 - dt * min(dfdm, 0.0)) if dfdm < 0 else dm * dt
        x.p1 = max(x.p1 + dp1 * dt, 1e5)
        x.p2 = max(x.p2 + dp2 * dt, 1e5)
        x.omega = max(x.omega + dw * dt, 0.0)
        x.asv = min(1.0, max(0.0, x.asv + d_asv * dt))
        x.time += dt
        self.m_feed, self.m_out, self.m_rec = m_feed, m_out, m_rec
        self.head, self.eta, self.pr, self.power, self.tau_comp = head, eta, pr, power, tau_comp

    # ---- slow dynamics -----------------------------------------------------
    def step_slow(self, dt: float) -> None:
        x, p, u, d = self.x, self.p, self.u, self.deg
        # Discharge temperature (algebraic, compressor residence time is short)
        if x.m_c > 0.5 and self.pr > 1:
            x.t2 = x.t1 * self.map.temperature_ratio(self.pr, self.eta)
        else:
            x.t2 += (x.t1 + 40.0 - x.t2) * dt / 30.0  # churning heats trapped gas
        # Aftercooler: effectiveness-NTU, crossflow both unmixed (Incropera eq. 11.32)
        fans = max(0, min(u.fans_cmd, p.n_fans) - len(d.fans_failed & set(range(u.fans_cmd))))
        air = p.air_flow_design * fans / p.n_fans + 0.08 * p.air_flow_design  # natural draft
        ua = p.ua_design * d.ua_factor * (air / p.air_flow_design) ** 0.6
        m_gas = max(x.m_c, 0.5)  # cooler sees full compressor flow
        c_gas, c_air = m_gas * p.cp_gas, air * 1007.0
        c_min, c_max = min(c_gas, c_air), max(c_gas, c_air)
        ntu, cr = ua / c_min, c_min / c_max
        eps = 1 - math.exp((ntu**0.22 / cr) * (math.exp(-cr * ntu**0.78) - 1))
        q = eps * c_min * (x.t2 - u.t_ambient)
        tc_ss = x.t2 - q / c_gas
        x.tc += (tc_ss - x.tc) * dt / p.tau_cooler_s
        # Suction temperature: feed mixed with cooled recycle
        m_in = max(self.m_feed, 0.0) + max(self.m_rec, 0.0)
        if m_in > 0.5:  # only inflows mix; during backflow the suction gas holds temperature
            t_mix = (max(self.m_feed, 0.0) * p.t_feed + max(self.m_rec, 0.0) * x.tc) / m_in
            x.t1 += (t_mix - x.t1) * dt / p.tau_suction_temp_s
        # Scrubber level: liquid in, LV out (Cv in US gpm/psi^0.5, linear trim)
        lv = d.lv_stuck if d.lv_stuck is not None else u.lv_cmd
        x.lv = lv
        dp_bar = max((x.p1 - p.p_drain) / 1e5, 0.0)
        q_out = 0.865 * p.lv_cv * lv * math.sqrt(dp_bar / (p.rho_liquid / 1000)) / 3600
        q_in = p.liquid_rate_m3_s + u.liquid_extra_m3_s
        x.level = max(0.0, min(1.5, x.level + (q_in - q_out) / p.scrubber_area * dt))
        # Bearing and winding temperatures (first order, 300 s)
        s2 = self.speed_ratio() ** 2
        load = self.power / max(p.motor_rated_w, 1)
        tde = 318.15 + 40 * s2 + 25 * d.bearing_wear_de**2
        x.t_bearing_de += (tde - x.t_bearing_de) * dt / 300
        x.t_bearing_nde += (318.15 + 37 * s2 - x.t_bearing_nde) * dt / 300
        x.t_thrust += (318.15 + 35 * s2 + 10 * load - x.t_thrust) * dt / 300
        x.t_winding += (u.t_ambient + 70 * load**2 - x.t_winding) * dt / 900

    # ---- truth for sensors -------------------------------------------------
    def vibration(self) -> tuple[float, float]:
        """Overall shaft vibration (um pk-pk) DE and NDE: 1X residual unbalance scaled with
        speed^2, bearing wear growth on DE, and broadband excitation during flow reversal."""
        s2 = self.speed_ratio() ** 2
        surge = 40.0 if self.x.m_c < 0.2 * self.p.m_design else 0.0
        de = 15 * s2 + 60 * self.deg.bearing_wear_de**1.5 + surge
        nde = 12 * s2 + surge * 0.8
        return de, nde

    def fe_dp(self) -> float:
        """Suction flow element differential pressure, Pa (dp = m^2 / (C^2 rho))."""
        c = self.p.m_design / math.sqrt(25e3 * self.p.rho1_design)
        m = max(self.x.m_c, 0.0)
        return m * m / (c * c * self.rho1())

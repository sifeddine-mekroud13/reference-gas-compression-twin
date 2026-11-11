"""Simulator parameters derived from the engineering dataset (no hardcoded equipment data).

Everything that describes the equipment comes from engineering/data via engdata. Values that
are modelling choices (time constants, effective lengths) are named and documented here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from engdata.dataset import Dataset, load
from engdata.sizing import run_sizing


@dataclass
class PlantParams:
    # Design point
    m_design: float  # kg/s
    p1_design: float  # Pa, compressor suction
    t1_design: float  # K
    p2_design: float  # Pa, compressor discharge
    t2_design: float  # K
    head_design: float  # J/kg, polytropic
    eta_design: float
    n_design_rpm: float
    n_min_rpm: float
    n_max_rpm: float
    temp_exponent_design: float  # m in T2/T1 = PR^m at design efficiency
    sigma_design: float  # (n-1)/n volume-based polytropic at design
    z1: float
    r_gas: float  # J/(kg K)
    rho1_design: float
    # Map shape (Moore-Greitzer cubic in normalized flow phi = Q/Q_design at design speed)
    phi_surge: float = 0.70
    psi_peak: float = 1.10
    eta_curvature: float = 0.8
    # Geometry
    a_c: float = 0.0  # m2, compressor duct area
    l_c: float = 0.0  # m, effective compressor duct length
    v_suction: float = 0.0  # m3
    v_discharge: float = 0.0  # m3
    inertia: float = 0.0  # kg m2 (rotor + motor)
    motor_rated_w: float = 0.0
    # Boundaries
    p_header_in: float = 30.5e5
    p_header_out: float = 75.0e5
    t_feed: float = 313.15
    k_feed: float = 0.0
    k_export: float = 0.0
    k_recycle: float = 0.0
    asv_stroke_s: float = 2.0
    # Scrubber
    scrubber_area: float = 0.0
    lv_cv: float = 4.0
    liquid_rate_m3_s: float = 0.0
    rho_liquid: float = 680.0
    p_drain: float = 2.0e5
    # Cooler
    ua_design: float = 0.0  # W/K at 4 fans
    n_fans: int = 4
    air_flow_design: float = 0.0  # kg/s, all fans
    cp_gas: float = 2700.0
    tau_cooler_s: float = 60.0
    tau_suction_temp_s: float = 20.0
    t_ambient_design: float = 323.15
    tc_setpoint: float = 333.15
    # Derived
    extras: dict[str, float] = field(default_factory=dict)

    @property
    def omega_design(self) -> float:
        return self.n_design_rpm * 2 * math.pi / 60

    @property
    def q_design(self) -> float:
        """Suction actual volume flow at design, m3/s."""
        return self.m_design / self.rho1_design


def _pipe_volume(ds: Dataset, ids: tuple[str, ...]) -> float:
    return float(sum(math.pi * (ln["dn"] / 1e3) ** 2 / 4 * ln["length_m"] for ln in ds.lines["lines"] if ln["id"] in ids))


def from_dataset(ds: Dataset | None = None) -> PlantParams:
    ds = ds or load()
    sz = run_sizing(ds).values
    eq = ds.equipment_by_tag()
    bod = ds.bod
    dc = bod["design_case"]
    k = eq["100-K-101"]["datasheet"]
    scr = eq["100-V-101"]["datasheet"]
    ac = eq["100-E-101"]["datasheet"]

    m = sz["mass_flow_kg_s"]
    p1 = sz["suction_pressure_bara"] * 1e5
    t1 = dc["scrubber_inlet_temperature_k"]
    p2 = dc["compressor_discharge_pressure_pa"]
    t2 = sz["discharge_temperature_c"] + 273.15
    pr = p2 / p1
    n_poly = sz["polytropic_exponent"]
    rho1 = m / sz["suction_actual_flow_m3_s"]
    r_gas = 8.314462618 / (sz["molar_mass_g_mol"] / 1e3)

    # Effective compressor duct (Greitzer L_c): internal flow path estimated at 0.4 m per
    # impeller plus 2 m of nozzles and volutes. Modelling assumption, see control philosophy.
    l_c = 0.4 * k["impellers"] + 2.0
    a_c = math.pi * 0.4**2 / 4  # suction nozzle DN400

    # Discharge plenum: piping up to recycle valve and check valve plus cooler tube volume.
    # Cooler tubes: 25.4 mm OD, 2.1 mm wall assumed; tube length from bare area.
    tube_len = ac["bare_tube_area_m2"] / (math.pi * 0.0254)
    v_cooler = math.pi * (0.0254 - 2 * 0.0021) ** 2 / 4 * tube_len * 1.15  # +15 % headers
    v_dis = _pipe_volume(ds, ("100-L-004", "100-L-005", "100-L-006", "100-L-008")) + v_cooler
    # Suction plenum: scrubber gas space at NLL plus suction-side piping.
    v_scr_gas = math.pi * scr["internal_diameter_m"] ** 2 / 4 * (scr["tan_tan_height_m"] - scr["nll_m"])
    v_suc = v_scr_gas + _pipe_volume(ds, ("100-L-002", "100-L-003", "100-L-009"))

    motor = eq["100-KM-101"]["datasheet"]
    inertia = motor["rotor_inertia_kg_m2"] + 0.5 * k["rotor_mass_kg"] * (k["impeller_diameter_m"] / 2) ** 2

    p_in = dc["scrubber_inlet_pressure_pa"]
    k_feed = m / math.sqrt(p_in + 0.5e5 - p1)  # header 0.5 bar above scrubber inlet
    p_out = dc["export_pressure_pa"]
    k_export = m / math.sqrt(p2 - p_out)
    # Recycle valve sized to pass 1.2 x design flow fully open at design differential
    rho2c = 52.0  # kg/m3 approx at 76 bara / 60 degC, refined by slow loop
    k_recycle = 1.2 * m / math.sqrt(rho2c * (p2 - p1))

    duty = sz["cooler_duty_mw"] * 1e6
    cp_gas = duty / (m * (t2 - dc["aftercooler_outlet_temperature_k"]))
    air = sz["air_mass_flow_kg_s"]
    ua = ac["u_bare_design_w_m2k"] * ac["bare_tube_area_m2"]

    sigma = (n_poly - 1) / n_poly
    p = PlantParams(
        m_design=m,
        p1_design=p1,
        t1_design=t1,
        p2_design=p2,
        t2_design=t2,
        head_design=sz["polytropic_head_kj_kg"] * 1e3,
        eta_design=dc["compressor_polytropic_efficiency"],
        n_design_rpm=k["design_speed_rpm"],
        n_min_rpm=k["min_speed_rpm"],
        n_max_rpm=k["max_continuous_speed_rpm"],
        temp_exponent_design=math.log(t2 / t1) / math.log(pr),
        sigma_design=sigma,
        z1=sz["suction_z"],
        r_gas=r_gas,
        rho1_design=rho1,
        a_c=a_c,
        l_c=l_c,
        v_suction=v_suc,
        v_discharge=v_dis,
        inertia=inertia,
        motor_rated_w=motor["rated_power_w"],
        p_header_in=p_in + 0.5e5,
        p_header_out=p_out,
        t_feed=t1,
        k_feed=k_feed,
        k_export=k_export,
        k_recycle=k_recycle,
        asv_stroke_s=eq["100-FV-2030"]["datasheet"]["stroke_time_open_s"],
        scrubber_area=math.pi * scr["internal_diameter_m"] ** 2 / 4,
        lv_cv=eq["100-LV-1103"]["datasheet"]["cv_max"],
        liquid_rate_m3_s=bod["feed_gas"]["free_liquid"]["normal_liquid_rate_m3_h"] / 3600,
        rho_liquid=bod["feed_gas"]["free_liquid"]["design_liquid_density_kg_m3"],
        ua_design=ua,
        n_fans=ac["bays"] * ac["fans_per_bay"],
        air_flow_design=air,
        cp_gas=cp_gas,
        t_ambient_design=bod["ambient"]["design_dry_bulb_k"],
        tc_setpoint=dc["aftercooler_outlet_temperature_k"],
    )
    a2 = 430.0
    omega_h = a2 * math.sqrt(a_c / (v_dis * l_c))
    u2 = sz["tip_speed_m_s"]
    p.extras.update(greitzer_b=u2 / (2 * omega_h * l_c), helmholtz_rad_s=omega_h, tip_speed=u2)
    return p

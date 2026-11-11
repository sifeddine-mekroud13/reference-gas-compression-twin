"""Design-case sizing verification.

The datasheets in engineering/data are the design. This module recomputes what each item
must be from the basis of design and checks the datasheet value is adequate. Results are
rendered to docs/sizing-calculations.md (generated, CI checks it is current).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from engdata.dataset import Dataset
from machinery import aircooler, separator
from machinery.compressor import polytropic_multistep
from thermo_ref import GasMixture

# Design-practice limits. Sources noted inline; all are rules of thumb to be reviewed.
PSI_RANGE = (
    0.40,
    0.60,
)  # polytropic head coefficient per impeller (Ludtke, Process Centrifugal Compressors)
U2_MAX = 320.0  # m/s, typical upper tip speed for process impellers (Ludtke; verify per material)
LINE_V_MAX = 20.0  # m/s, compressor suction/discharge line velocity design practice (verify vs NORSOK P-002)
FAN_STATIC_PA = 200.0  # Pa, assumed fan static pressure for a forced-draft ACHE
FAN_EFF = 0.65  # assumed fan total efficiency
RHO_AIR_IN = 1.08  # kg/m3, air at 50 degC near sea level (ideal gas, 101 kPa)
MECH_EFF = 0.985  # bearing and seal losses (assumption)


@dataclass
class Check:
    item: str
    quantity: str
    required: float
    provided: float
    unit: str
    passed: bool
    note: str = ""


@dataclass
class SizingResult:
    values: dict[str, float] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)


MAX_OVERSIZE = 1.6  # flag gross oversizing: it hides control problems (e.g. overcooling)


def _ge(item: str, q: str, req: float, prov: float, unit: str, note: str = "") -> Check:
    ok = req <= prov <= MAX_OVERSIZE * req
    return Check(item, q, req, prov, unit, ok, f"{note}; must not exceed {MAX_OVERSIZE} x required")


def run_sizing(ds: Dataset) -> SizingResult:
    res = SizingResult()
    v = res.values
    bod: dict[str, Any] = ds.bod
    dc = bod["design_case"]
    eq = ds.equipment_by_tag()
    gas = GasMixture(bod["feed_gas"]["composition"])

    m = gas.mass_flow_from_standard(dc["standard_flow_sm3_d"])
    v["mass_flow_kg_s"] = m
    v["molar_mass_g_mol"] = gas.molar_mass * 1e3
    v["standard_density_kg_sm3"] = gas.standard_density()

    # Scrubber
    p_scr = dc["scrubber_inlet_pressure_pa"] - dc["scrubber_pressure_drop_pa"]
    t1 = dc["scrubber_inlet_temperature_k"]
    st_scr = gas.state_pt(p_scr, t1)
    scr = eq["100-V-101"]["datasheet"]
    rho_l = bod["feed_gas"]["free_liquid"]["design_liquid_density_kg_m3"]
    k = scr["demister_k_design_m_s"] * separator.k_derating(p_scr - 101_325.0)
    vmax = separator.souders_brown_vmax(k, rho_l, st_scr.rho)
    q_size = dc["scrubber_sizing_flow_factor"] * m / st_scr.rho
    d_req = separator.min_diameter(q_size, vmax)
    v.update(scrubber_k_derated=k, scrubber_vmax=vmax, scrubber_q_sizing=q_size, scrubber_d_req=d_req)
    v["scrubber_load_design"] = separator.load_factor(m / st_scr.rho, scr["internal_diameter_m"], rho_l, st_scr.rho) / k
    res.checks.append(
        _ge(
            "100-V-101",
            "internal diameter",
            d_req,
            scr["internal_diameter_m"],
            "m",
            "Souders-Brown, mesh pad, GPSA pressure derating",
        )
    )

    # Compressor design point
    p1 = p_scr - dc["suction_line_pressure_drop_pa"]
    p2 = dc["compressor_discharge_pressure_pa"]
    comp = polytropic_multistep(gas, p1, t1, p2, dc["compressor_polytropic_efficiency"])
    kd = eq["100-K-101"]["datasheet"]
    power = m * comp.work_specific / MECH_EFF
    v.update(
        suction_pressure_bara=p1 / 1e5,
        discharge_temperature_c=comp.outlet.t - 273.15,
        polytropic_head_kj_kg=comp.head_polytropic / 1e3,
        gas_power_mw=m * comp.work_specific / 1e6,
        shaft_power_mw=power / 1e6,
        suction_actual_flow_m3_s=m / comp.inlet.rho,
        suction_z=comp.inlet.z,
        polytropic_exponent=comp.n_polytropic,
    )
    u2 = math.pi * kd["impeller_diameter_m"] * kd["design_speed_rpm"] / 60.0
    psi = comp.head_polytropic / kd["impellers"] / u2**2
    v.update(tip_speed_m_s=u2, head_coefficient=psi)
    res.checks.append(
        Check(
            "100-K-101",
            "head coefficient per impeller",
            PSI_RANGE[0],
            psi,
            "-",
            PSI_RANGE[0] <= psi <= PSI_RANGE[1],
            f"must lie in {PSI_RANGE} (Ludtke)",
        )
    )
    res.checks.append(
        Check(
            "100-K-101",
            "impeller tip speed limit",
            U2_MAX,
            u2,
            "m/s",
            u2 <= U2_MAX,
            f"must be <= {U2_MAX} m/s",
        )
    )

    # Driver: rated point = rated speed fraction, fan laws (Q ~ N, H ~ N^2, P ~ N^3)
    nr = dc["rated_speed_fraction"]
    p_rated = power * nr**3
    margin = bod["design_margins"]["driver_power_margin"]
    v["rated_point_shaft_power_mw"] = p_rated / 1e6
    res.checks.append(
        _ge(
            "100-KM-101",
            "motor rated power",
            margin * p_rated,
            eq["100-KM-101"]["datasheet"]["rated_power_w"],
            "W",
            f"{margin:.2f} x shaft power at {nr:.2f} speed (fan laws)",
        )
    )

    # Aftercooler
    p_cool_out = p2 - dc["aftercooler_pressure_drop_pa"]
    t_out = dc["aftercooler_outlet_temperature_k"]
    h_out = gas.state_pt(p_cool_out, t_out).h
    duty = m * (comp.outlet.h - h_out)
    ac = eq["100-E-101"]["datasheet"]
    t_air_in = bod["ambient"]["design_dry_bulb_k"]
    t_air_out = t_air_in + ac["design_air_temperature_rise_k"]
    lmtd = aircooler.lmtd_counterflow(comp.outlet.t, t_out, t_air_in, t_air_out)
    a_req = aircooler.required_area(duty, ac["u_bare_design_w_m2k"], ac["lmtd_correction_factor"], lmtd)
    a_margin = bod["design_margins"]["aftercooler_area_margin"]
    m_air = aircooler.air_mass_flow(duty, ac["design_air_temperature_rise_k"])
    fan_shaft = m_air / RHO_AIR_IN * FAN_STATIC_PA / FAN_EFF
    n_fans = ac["bays"] * ac["fans_per_bay"]
    v.update(
        cooler_duty_mw=duty / 1e6,
        cooler_lmtd_k=lmtd,
        cooler_area_req_m2=a_req,
        cooler_approach_k=t_out - t_air_in,
        air_mass_flow_kg_s=m_air,
        fan_shaft_power_each_kw=fan_shaft / n_fans / 1e3,
    )
    res.checks.append(
        _ge(
            "100-E-101",
            "bare tube area",
            a_margin * a_req,
            ac["bare_tube_area_m2"],
            "m2",
            f"{a_margin:.2f} x required, U={ac['u_bare_design_w_m2k']} W/m2K assumed",
        )
    )
    fan_rated = min(eq[f"100-EM-101{c}"]["datasheet"]["rated_power_w"] for c in "ABCD")
    res.checks.append(
        _ge(
            "100-EM-101A..D",
            "fan motor rating",
            1.1 * fan_shaft / n_fans,
            fan_rated,
            "W",
            f"1.1 x fan shaft power at {FAN_STATIC_PA:.0f} Pa static, eta {FAN_EFF}",
        )
    )

    # Line velocities (DN used as internal diameter: approximation, refine with schedules)
    rho_by_line = {
        "100-L-003": comp.inlet.rho,
        "100-L-004": comp.outlet.rho,
        "100-L-005": gas.state_pt(p_cool_out, t_out).rho,
    }
    for ln in ds.lines["lines"]:
        if ln["id"] in rho_by_line:
            area = math.pi * (ln["dn"] / 1e3) ** 2 / 4
            vel = m / rho_by_line[ln["id"]] / area
            v[f"velocity_{ln['id']}"] = vel
            res.checks.append(
                Check(
                    ln["id"],
                    "gas velocity limit",
                    LINE_V_MAX,
                    vel,
                    "m/s",
                    vel <= LINE_V_MAX,
                    f"must be <= {LINE_V_MAX} m/s",
                )
            )

    # Discharge-side volume for the Greitzer plenum (M2 uses it). Piping only; cooler
    # internal volume added in M2 from tube geometry.
    plenum_lines = ("100-L-004", "100-L-005", "100-L-006", "100-L-008")
    vol = sum(math.pi * (ln["dn"] / 1e3) ** 2 / 4 * ln["length_m"] for ln in ds.lines["lines"] if ln["id"] in plenum_lines)
    v["discharge_piping_volume_m3"] = vol
    return res


def render_markdown(res: SizingResult) -> str:
    v = res.values
    rows = "\n".join(
        f"| {c.item} | {c.quantity} | {c.required:.4g} | {c.provided:.4g} | {c.unit} | "
        f"{'PASS' if c.passed else 'FAIL'} | {c.note} |"
        for c in res.checks
    )
    vals = "\n".join(f"| `{k}` | {val:.5g} |" for k, val in v.items())
    return f"""<!-- GENERATED by `engdata sizing --write`. Do not edit by hand. -->
# Sizing calculations, Unit 100 (design case)

Inputs: `engineering/data/basis_of_design.yaml` and equipment datasheets.
Method and sources: see the docstrings of `libs/machinery` and `libs/engdata/src/engdata/sizing.py`,
and the narrative in [basis-of-design.md](basis-of-design.md).

## Datasheet verification

| Item | Quantity | Required / limit | Datasheet / actual | Unit | Result | Basis |
|---|---|---|---|---|---|---|
{rows}

## Computed design values

| Quantity | Value |
|---|---|
{vals}

## Values to cross-check independently (DWSIM or hand calculation)

1. Suction density and Z at scrubber conditions (DWSIM, GERG-2008 property package if available, else Peng-Robinson and expect about 1 percent deviation).
2. Compressor discharge temperature and gas power at the design polytropic efficiency (DWSIM compressor block in polytropic mode).
3. Aftercooler duty between discharge temperature and cooler outlet temperature (DWSIM cooler block).
4. Scrubber minimum diameter by hand from the Souders-Brown equation with the densities above.
"""

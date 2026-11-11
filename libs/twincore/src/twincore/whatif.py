"""What-if engine: forks the calibrated twin state and evaluates scenarios faster than real time.

Two modes:
* steady(): quasi-steady evaluation with the TwinModel (hours to months: ambient, flow,
  fouling trend, wash vs no wash). Solves for the speed that meets the discharge pressure.
* transient(): short dynamic run of the Greitzer simulator initialized with the estimated
  degradation (setpoint steps, export pressure upsets), checking surge and trips.
Returned constraint checks: surge margin above the control line, discharge temperature below
its H alarm, motor power below rating.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from scipy.optimize import brentq

from twincore.model import K0, Operating, TwinModel

T2_LIMIT_C = 145.0
SM_LIMIT = 15.0


@dataclass(frozen=True)
class Scenario:
    flow_factor: float = 1.0
    ambient_c: float = 45.0
    p_suction_bar: float = 29.0
    p_discharge_bar: float = 76.0
    f_head: float = 1.0
    f_eta: float = 1.0
    f_ua: float = 1.0
    fans: int = 4


def steady(model: TwinModel, sc: Scenario) -> dict[str, Any]:
    p = model.p
    m = p.m_design * sc.flow_factor
    t1 = p.t1_design
    pr_req = sc.p_discharge_bar / sc.p_suction_bar

    def resid(n: float) -> float:
        op = Operating(m, n, sc.p_suction_bar * 1e5, t1, sc.ambient_c + K0, sc.fans)
        return model.predict(op, sc.f_head, sc.f_eta, sc.f_ua).pr - pr_req

    lo, hi = p.n_min_rpm * 0.9, p.n_max_rpm * 1.15
    try:
        n = brentq(resid, lo, hi, xtol=0.5)
        feasible_speed = n <= p.n_max_rpm
    except ValueError:
        n, feasible_speed = hi, False
    pred = model.predict(Operating(m, n, sc.p_suction_bar * 1e5, t1, sc.ambient_c + K0, sc.fans), sc.f_head, sc.f_eta, sc.f_ua)
    power_mw = pred.power / 0.97 / 1e6
    violations = []
    if not feasible_speed:
        violations.append("required speed above maximum continuous speed")
    if pred.t2 - K0 > T2_LIMIT_C:
        violations.append(f"discharge temperature above {T2_LIMIT_C} degC")
    if pred.surge_margin < SM_LIMIT:
        violations.append(f"surge margin below {SM_LIMIT} percent (recycle needed)")
    if power_mw * 1e6 > p.motor_rated_w:
        violations.append("motor power above rating")
    return {
        "scenario": asdict(sc),
        "speed_rpm": n,
        "discharge_temp_c": pred.t2 - K0,
        "power_mw": power_mw,
        "cooler_outlet_c": pred.tc - K0,
        "surge_margin_pct": pred.surge_margin,
        "specific_energy_kwh_per_t": power_mw * 1e3 / (m * 3.6),
        "violations": violations,
    }


def wash_economics(
    f_eta_now: float,
    eta_loss_per_day: float,
    power_mw: float,
    price_per_mwh: float,
    wash_cost: float,
    recovery: float = 0.8,
    horizon_days: int = 365,
) -> dict[str, Any]:
    """Optimal offline wash interval for linear efficiency decay (classic sawtooth model).

    Extra power ~ P * (1/f - 1); for small losses and linear decay r per day, the extra energy
    cost over an interval T is C_e * P * r * T^2 / 2, so cost rate = wash_cost/T + C_e P r T / 2,
    minimized at T* = sqrt(2 wash_cost / (C_e P r)) with C_e in per-day units.
    Recovery < 1 leaves a non-recoverable residual (not optimized here).
    """
    c_day = price_per_mwh * 24 * power_mw  # cost of running one day at full power
    r = max(eta_loss_per_day * recovery, 1e-9)
    t_star = (2 * wash_cost / (c_day * r)) ** 0.5
    current_loss_cost_day = c_day * (1 / f_eta_now - 1)
    return {
        "optimal_interval_days": t_star,
        "current_extra_cost_per_day": current_loss_cost_day,
        "wash_now": current_loss_cost_day * t_star / 2 > wash_cost and f_eta_now < 0.99,
        "horizon_days": horizon_days,
    }


def optimize_suction_setpoint(model: TwinModel, base: Scenario, candidates: list[float]) -> dict[str, Any]:
    """Prescriptive example: choose the suction pressure setpoint with the lowest specific energy
    that violates no constraint. Throughput is held (flow_factor fixed)."""
    results = [steady(model, Scenario(**{**asdict(base), "p_suction_bar": c})) for c in candidates]
    ok = [r for r in results if not r["violations"]]
    best = min(ok, key=lambda r: r["specific_energy_kwh_per_t"]) if ok else None
    return {"candidates": results, "best": best}

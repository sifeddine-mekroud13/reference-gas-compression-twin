"""Level 3 twin service (ADR 0005): calculation, synchronization, prognosis and advisory.

Every cycle (30 s wall clock):
1. Read the latest values and a 5 min window from the historian.
2. Compute PTC 10-style KPIs; store them as TWIN.* tags.
3. If the window is steady, update the UKF (degradation factors). The first steady updates
   after start-up define the commissioning baseline; reported degradation is relative to it.
4. Trend the efficiency factor for a remaining-useful-life estimate (time to the wash limit).
5. Every 10 cycles, run the what-if setpoint optimizer and, if the saving is material, submit
   an advisory to the DCS (OPC UA method Submit). The operator decides at the DCS.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from typing import Any

import asyncpg
import numpy as np
from asyncua import ua

from engdata.dataset import load
from plant.params import from_dataset
from svc_common import config
from svc_opcua.hmi import client as ua_client
from thermo_ref import GasMixture
from twincore.kpi import all_kpis, is_steady
from twincore.model import TwinModel
from twincore.sync import Synchronizer
from twincore.whatif import Scenario, optimize_suction_setpoint, wash_economics

log = logging.getLogger("twin")
UTC = dt.UTC
STEADY_TAGS = ("100-PT-2002", "100-PT-2004", "100-FY-2001", "100-ST-2020", "100-TT-2005", "100-TT-3001")
BASELINE_UPDATES = 10
ETA_WASH_LIMIT = 0.93
ADVISORY_EVERY = 10
MIN_SAVING = 0.01


async def latest(conn: asyncpg.Connection) -> tuple[dict[str, float], dt.datetime | None]:
    rows = await conn.fetch(
        "SELECT DISTINCT ON (tag) tag, value, ts FROM sample WHERE tag NOT LIKE 'TWIN.%' "
        "AND quality LIKE 'Good%' ORDER BY tag, ts DESC"
    )
    vals = {r["tag"]: r["value"] for r in rows if r["value"] is not None}
    t = max((r["ts"] for r in rows), default=None)
    return vals, t


async def window(conn: asyncpg.Connection, t_end: dt.datetime, seconds: float) -> dict[str, list[float]]:
    rows = await conn.fetch(
        "SELECT tag, value FROM sample_raw WHERE tag = ANY($1) AND ts > $2 AND ts <= $3 ORDER BY ts",
        list(STEADY_TAGS),
        t_end - dt.timedelta(seconds=seconds),
        t_end,
    )
    out: dict[str, list[float]] = {t: [] for t in STEADY_TAGS}
    for r in rows:
        if r["value"] is not None:
            out[r["tag"]].append(r["value"])
    return out


async def store(conn: asyncpg.Connection, ts: dt.datetime, values: dict[str, float]) -> None:
    await conn.executemany(
        "INSERT INTO sample (ts, tag, value, quality) VALUES ($1,$2,$3,'Good') ON CONFLICT DO NOTHING",
        [(ts, f"TWIN.{k}", float(v)) for k, v in values.items() if np.isfinite(v)],
    )


def rul_days(history: list[tuple[float, float]]) -> float:
    """Days until the relative efficiency factor reaches the wash limit, by linear trend."""
    if len(history) < 5:
        return float("nan")
    t = np.array([h[0] for h in history]) / 86400
    y = np.array([h[1] for h in history])
    slope, intercept = np.polyfit(t, y, 1)
    if slope >= -1e-6:
        return float("inf")
    return float(max((ETA_WASH_LIMIT - (intercept + slope * t[-1])) / slope, 0.0))


async def submit_advisory(target: str, value: float, rationale: str) -> str:
    c = await ua_client("twin")
    async with c:
        idx = await c.get_namespace_index("urn:rgpf:unit100")
        folder = c.get_node(ua.NodeId("Advisory", idx))
        adv_id = f"ADV-{uuid.uuid4().hex[:8]}"
        res = await folder.call_method(f"{idx}:Submit", adv_id, target, value, rationale)
        return f"{adv_id}:{res}"


async def mirror_advisory(conn: asyncpg.Connection) -> None:
    c = await ua_client("twin")
    async with c:
        idx = await c.get_namespace_index("urn:rgpf:unit100")
        f = {
            k: await c.get_node(ua.NodeId(f"ADV.{k}", idx)).read_value()
            for k in ("Id", "TargetTag", "ProposedValue", "Rationale", "State", "DecidedBy")
        }
    if f["Id"]:
        await conn.execute(
            "INSERT INTO advisory (id, target, value, rationale, state, decided_by, decided_at) "
            "VALUES ($1,$2,$3,$4,$5,$6, CASE WHEN $5 IN ('ACCEPTED','REJECTED','BLOCKED') THEN now() END) "
            "ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state, decided_by = EXCLUDED.decided_by, "
            "decided_at = COALESCE(advisory.decided_at, EXCLUDED.decided_at)",
            f["Id"],
            f["TargetTag"],
            f["ProposedValue"],
            f["Rationale"],
            f["State"],
            f["DecidedBy"] or None,
        )


async def cycle(conn: asyncpg.Connection, st: dict[str, Any]) -> None:
    vals, t = await latest(conn)
    needed = set(STEADY_TAGS) | {"100-PT-1101", "100-TT-1102", "100-PT-3002", "100-TT-3003", "100-TT-2003", "100-JT-2102"}
    if t is None or not needed <= vals.keys():
        log.info("waiting for data")
        return
    if vals.get("TRIP", 0) > 0.5 or vals["100-FY-2001"] < 5:
        log.info("compressor not running, skipping")
        return
    k = all_kpis(st["gas"], vals, st["k_design"], st["d_scr"], st["rho_l"])
    out = {
        "eta_p": k.eta_p * 100,
        "eta_p_u95": k.eta_p_u95 * 100,
        "head_p": k.head_p_kj,
        "cooler_approach": k.cooler_approach_k,
        "cooler_duty": k.cooler_duty_mw,
        "scrubber_load": k.scrubber_load,
    }
    steady = is_steady(await window(conn, t, 300))
    out["steady"] = 1.0 if steady else 0.0
    if steady:
        est = st["sync"].update(vals)
        st["n"] += 1
        if st["n"] <= BASELINE_UPDATES:
            st["base"] = (est["f_head"], est["f_eta"], est["f_ua"])
        b = st["base"]
        rel = {"f_head_rel": est["f_head"] / b[0], "f_eta_rel": est["f_eta"] / b[1], "f_ua_rel": est["f_ua"] / b[2]}
        out.update(rel)
        out.update({"sd_eta": est["sd_eta"], "calibrated": 1.0 if st["n"] > BASELINE_UPDATES else 0.0})
        if st["n"] > BASELINE_UPDATES:
            st["eta_hist"].append((t.timestamp(), rel["f_eta_rel"]))
            st["eta_hist"] = st["eta_hist"][-200:]
            out["rul_days"] = rul_days(st["eta_hist"])
            w = wash_economics(rel["f_eta_rel"], 0.0005, vals["100-JT-2102"], 60.0, 20000.0)
            out["wash_recommended"] = 1.0 if w["wash_now"] else 0.0
    await store(conn, t, out)
    st["cycle"] += 1
    if st["cycle"] % ADVISORY_EVERY == 0 and st["n"] > BASELINE_UPDATES:
        sc = Scenario(
            flow_factor=vals["100-FY-2001"] / st["model"].p.m_design,
            ambient_c=vals["100-TT-3003"],
            p_suction_bar=vals["100-PT-2002"],
            p_discharge_bar=vals["100-PT-2004"],
            f_head=st["sync"].ukf.x[0],
            f_eta=st["sync"].ukf.x[1],
            f_ua=st["sync"].ukf.x[2],
        )
        opt = optimize_suction_setpoint(st["model"], sc, [27.5, 28.0, 28.5, 29.0, 29.5, 30.0, 30.5])
        cur = next(r for r in opt["candidates"] if abs(r["scenario"]["p_suction_bar"] - 29.0) < 1e-6)
        best = opt["best"]
        if best and best["specific_energy_kwh_per_t"] < cur["specific_energy_kwh_per_t"] * (1 - MIN_SAVING):
            sp = best["scenario"]["p_suction_bar"]
            saving = 1 - best["specific_energy_kwh_per_t"] / cur["specific_energy_kwh_per_t"]
            msg = (
                f"Raise suction pressure setpoint to {sp:.1f} bara: predicted specific energy "
                f"-{saving * 100:.1f} percent, surge margin {best['surge_margin_pct']:.0f} percent, "
                f"discharge {best['discharge_temp_c']:.0f} degC. Check upstream separator pressure first."
            )
            try:
                log.info("advisory: %s", await submit_advisory("100-PIC-2002.SP", sp, msg))
            except Exception as e:
                log.warning("advisory submit failed: %s", e)
    try:
        await mirror_advisory(conn)
    except Exception as e:
        log.warning("advisory mirror failed: %s", e)
    log.info("cycle %d steady=%s eta=%.2f%% n=%d", st["cycle"], steady, k.eta_p * 100, st["n"])


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("asyncua").setLevel(logging.ERROR)
    ds = load()
    params = from_dataset(ds)
    model = TwinModel(params)
    scr = ds.equipment_by_tag()["100-V-101"]["datasheet"]
    st: dict[str, Any] = {
        "gas": GasMixture(ds.bod["feed_gas"]["composition"]),
        "model": model,
        "sync": Synchronizer(model),
        "k_design": scr["demister_k_design_m_s"],
        "d_scr": scr["internal_diameter_m"],
        "rho_l": ds.bod["feed_gas"]["free_liquid"]["design_liquid_density_kg_m3"],
        "n": 0,
        "cycle": 0,
        "base": (1.0, 1.0, 1.0),
        "eta_hist": [],
    }
    period = float(config.env("RGPF_TWIN_PERIOD_S", "30"))
    while True:
        try:
            conn = await asyncpg.connect(config.HISTORIAN_DSN, timeout=5)
            try:
                while True:
                    await cycle(conn, st)
                    await asyncio.sleep(period)
            finally:
                await conn.close()
        except (TimeoutError, OSError, asyncpg.PostgresError) as e:
            log.warning("historian unavailable: %s", e)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())

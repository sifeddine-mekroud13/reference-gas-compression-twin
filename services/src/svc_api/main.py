"""Level 4 platform API (read-only towards the plant). Versioned under /api/v1."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from engdata.dataset import REPO_ROOT, load
from plant.params import from_dataset
from svc_api import graph
from svc_api.auth import User, require, ws_user
from svc_common import config
from twincore.model import TwinModel
from twincore.whatif import Scenario, steady

log = logging.getLogger("api")
ALL = ("operator", "process_engineer", "maintenance")
ENG = ("process_engineer", "maintenance")
STATE: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    ds = load()
    params = from_dataset(ds)
    STATE.update(ds=ds, params=params, model=TwinModel(params))
    for _ in range(60):
        try:
            STATE["pool"] = await asyncpg.create_pool(config.REPLICA_DSN, min_size=1, max_size=8)
            break
        except (OSError, asyncpg.PostgresError):
            await asyncio.sleep(2)
    async with STATE["pool"].acquire() as c:
        n = await graph.build(c, ds)
        log.info("asset graph built: %d nodes", n)
    yield
    await STATE["pool"].close()


app = FastAPI(title="RGPF Unit 100 platform API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.env("RGPF_CORS", "http://localhost:8081").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["authorization", "content-type"],
)


@app.middleware("http")
async def audit(request: Request, call_next: Any) -> Response:
    resp: Response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/v1/") and path != "/api/v1/health" and "pool" in STATE:
        u: User | None = getattr(request.state, "user", None)
        try:
            async with STATE["pool"].acquire() as c:
                await c.execute(
                    "INSERT INTO audit_log (subject, username, roles, method, path, status, detail) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)",
                    u.sub if u else None,
                    u.username if u else None,
                    u.roles if u else None,
                    request.method,
                    path + ("?" + request.url.query if request.url.query else ""),
                    resp.status_code,
                    json.dumps(getattr(request.state, "audit_detail", {})),
                )
        except Exception as e:  # auditing must not take the API down, but it must be visible
            log.error("audit write failed: %s", e)
    return resp


async def q(sql: str, *args: Any) -> list[dict[str, Any]]:
    async with STATE["pool"].acquire() as c:
        return [dict(r) for r in await c.fetch(sql, *args)]


@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    rows = await q("SELECT max(ts) AS last FROM sample")
    return {"status": "ok", "last_sample": rows[0]["last"]}


@app.get("/api/v1/me")
async def me(user: User = require(*ALL)) -> dict[str, Any]:
    return {"username": user.username, "roles": user.roles}


@app.get("/api/v1/assets")
async def assets(user: User = require(*ALL)) -> list[dict[str, Any]]:
    return await q("SELECT id, kind, name, path::text AS path FROM graph.node WHERE path IS NOT NULL ORDER BY path")


@app.get("/api/v1/assets/{node_id}")
async def asset(node_id: str, user: User = require(*ALL)) -> dict[str, Any]:
    async with STATE["pool"].acquire() as c:
        ctx = await graph.context(c, node_id)
    if ctx is None:
        raise HTTPException(404, "unknown node")
    tags = [o["name"] for o in ctx["outgoing"] if o["kind"] == "tag"]
    ctx["live"] = await q(
        "SELECT DISTINCT ON (tag) tag, value, quality, ts FROM sample WHERE tag = ANY($1) ORDER BY tag, ts DESC", tags
    )
    if "maintenance" in user.roles or "process_engineer" in user.roles or "admin" in user.roles:
        ctx["work_orders"] = await q(
            "SELECT * FROM work_order WHERE functional_location=$1 ORDER BY reported DESC", ctx["node"]["name"]
        )
    return ctx


@app.get("/api/v1/scene")
async def scene(user: User = require(*ALL)) -> dict[str, Any]:
    """Procedural 3D scene description generated from datasheets and layout (no CAD files)."""
    ds = STATE["ds"]
    eq = [
        {
            "tag": e["tag"],
            "cls": e["iso14224_class"],
            "type": e["type"],
            "pos": ds.layout["equipment"][e["tag"]]["pos3d"],
            "ds": {k: v for k, v in e["datasheet"].items() if isinstance(v, int | float)},
        }
        for e in ds.equipment
    ]
    return {
        "equipment": eq,
        "lines": [{"id": ln["id"], "from": ln["from"], "to": ln["to"], "dn": ln["dn"]} for ln in ds.lines["lines"]],
    }


@app.get("/api/v1/tags")
async def tags(user: User = require(*ALL)) -> list[dict[str, Any]]:
    return [
        {k: t[k] for k in ("tag", "class", "desc", "equipment", "range", "nominal")} | {"unit": t["unit"]["symbol"]}
        for t in STATE["ds"].tags
    ]


async def live_values() -> list[dict[str, Any]]:
    return await q(
        "SELECT DISTINCT ON (tag) tag, value, quality, ts FROM sample "
        "WHERE ts > (SELECT max(ts) FROM sample) - interval '2 hours' ORDER BY tag, ts DESC"
    )


@app.get("/api/v1/live")
async def live(user: User = require(*ALL)) -> list[dict[str, Any]]:
    return await live_values()


@app.get("/api/v1/history")
async def history(
    tag: str,
    minutes: int = Query(60, le=60 * 24 * 30),
    bucket_s: int = Query(0, ge=0),
    end: dt.datetime | None = None,
    user: User = require(*ENG),
) -> list[dict[str, Any]]:
    end_sql = "COALESCE($3, (SELECT max(ts) FROM sample))"
    if bucket_s:
        return await q(
            f"SELECT to_timestamp(floor(extract(epoch FROM ts) / $4) * $4) AS ts, avg(value) AS value, "
            f"min(value) AS min, max(value) AS max FROM sample WHERE tag=$1 AND ts > {end_sql} - "
            f"make_interval(mins => $2) AND ts <= {end_sql} GROUP BY 1 ORDER BY 1",
            tag,
            minutes,
            end,
            float(bucket_s),
        )
    return await q(
        f"SELECT ts, value, quality FROM sample WHERE tag=$1 AND ts > {end_sql} - make_interval(mins => $2) "
        f"AND ts <= {end_sql} ORDER BY ts",
        tag,
        minutes,
        end,
    )


@app.get("/api/v1/alarms")
async def alarms(user: User = require(*ALL)) -> dict[str, Any]:
    defs = {f"{a['tag']}.{a['type']}": a for a in STATE["ds"].alarms}
    cur = await q("SELECT DISTINCT ON (alarm) alarm, state, ts FROM alarm_event ORDER BY alarm, ts DESC")
    standing = [
        c
        | {
            "priority": defs[c["alarm"]]["priority"],
            "action": defs[c["alarm"]]["action"],
            "consequence": defs[c["alarm"]]["consequence"],
        }
        for c in cur
        if c["alarm"] in defs and c["state"] in ("UNACK", "ACKED", "RTNUN")
    ]
    events = await q("SELECT * FROM alarm_event WHERE state <> 'NORM' ORDER BY ts DESC LIMIT 200")
    last = await q("SELECT max(ts) AS t FROM alarm_event")
    t = last[0]["t"]
    rate = (
        (
            await q(
                "SELECT count(*) AS n FROM alarm_event WHERE state='UNACK' AND ts > $1::timestamptz - interval '10 minutes'", t
            )
        )[0]["n"]
        if t
        else 0
    )
    return {
        "standing": sorted(standing, key=lambda a: a["priority"]),
        "events": events,
        "rate_per_10min": rate,
        "flood": rate > 10,
    }


@app.get("/api/v1/kpis")
async def kpis(user: User = require(*ALL)) -> list[dict[str, Any]]:
    return await q("SELECT DISTINCT ON (tag) tag, value, ts FROM sample WHERE tag LIKE 'TWIN.%' ORDER BY tag, ts DESC")


@app.get("/api/v1/surge-map")
async def surge_map(user: User = require(*ALL)) -> dict[str, Any]:
    m = STATE["model"].map
    p = STATE["params"]
    zrt = p.z1 * p.r_gas * p.t1_design
    lines = []
    for s in (0.7, 0.8, 0.9, 1.0, 1.05):
        pts = []
        q_s = m.surge_flow(s, zrt)
        for i in range(25):
            qv = q_s + i * (1.35 * p.q_design * s - q_s) / 24
            h = m.head(qv, s)
            pts.append({"q": qv, "head_kj": h / 1e3})
        lines.append({"speed": s, "points": pts, "surge": {"q": q_s, "head_kj": m.head(q_s, s) / 1e3}})
    lv = {r["tag"]: r["value"] for r in await live_values()}
    op = None
    if {"100-FY-2001", "100-PT-2002", "100-TT-2003", "TWIN.head_p"} <= lv.keys():
        rho = lv["100-PT-2002"] * 1e5 / (p.z1 * p.r_gas * (lv["100-TT-2003"] + 273.15))
        op = {"q": lv["100-FY-2001"] / rho, "head_kj": lv["TWIN.head_p"], "surge_margin": lv.get("100-UY-2042")}
    return {"speed_lines": lines, "operating_point": op, "note": "synthetic map, see docs/control-philosophy.md"}


class WhatIf(BaseModel):
    flow_factor: float = Field(1.0, ge=0.5, le=1.3)
    ambient_c: float = Field(45.0, ge=-10, le=60)
    p_suction_bar: float = Field(29.0, ge=20, le=35)
    p_discharge_bar: float = Field(76.0, ge=50, le=95)
    use_estimated_degradation: bool = True
    f_eta_override: float | None = Field(None, ge=0.7, le=1.05)
    fans: int = Field(4, ge=0, le=4)


@app.post("/api/v1/whatif")
async def whatif(body: WhatIf, request: Request, user: User = require("process_engineer")) -> dict[str, Any]:
    """Computed at Level 4 from the replicated twin state. Nothing is sent to the plant."""
    kp = {r["tag"]: r["value"] for r in await kpis(user)}
    fh = kp.get("TWIN.f_head_rel", 1.0) if body.use_estimated_degradation else 1.0
    fe = body.f_eta_override or (kp.get("TWIN.f_eta_rel", 1.0) if body.use_estimated_degradation else 1.0)
    fu = kp.get("TWIN.f_ua_rel", 1.0) if body.use_estimated_degradation else 1.0
    sc = Scenario(body.flow_factor, body.ambient_c, body.p_suction_bar, body.p_discharge_bar, fh, fe, fu, body.fans)
    res = steady(STATE["model"], sc)
    request.state.audit_detail = {"whatif": body.model_dump()}
    return res


@app.get("/api/v1/twin/degradation")
async def degradation(minutes: int = 600, user: User = require(*ENG)) -> dict[str, Any]:
    out = {}
    for t in ("TWIN.f_eta_rel", "TWIN.f_head_rel", "TWIN.f_ua_rel", "TWIN.eta_p", "TWIN.rul_days"):
        out[t] = await q(
            "SELECT ts, value FROM sample WHERE tag=$1 AND ts > (SELECT max(ts) FROM sample) - "
            "make_interval(mins => $2) ORDER BY ts",
            t,
            minutes,
        )
    return out


@app.get("/api/v1/advisories")
async def advisories(user: User = require(*ALL)) -> list[dict[str, Any]]:
    return await q("SELECT * FROM advisory ORDER BY created DESC LIMIT 50")


@app.get("/api/v1/workorders")
async def workorders(user: User = require(*ENG)) -> list[dict[str, Any]]:
    return await q("SELECT * FROM work_order ORDER BY reported DESC")


@app.get("/api/v1/audit")
async def audit_log(user: User = require("admin")) -> list[dict[str, Any]]:
    return await q("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")


@app.get("/api/v1/diode")
async def diode(user: User = require(*ALL)) -> list[dict[str, Any]]:
    return await q("SELECT * FROM diode_status")


@app.get("/api/v1/pid.svg")
async def pid_svg(user: User = require(*ALL)) -> FileResponse:
    f = REPO_ROOT / "engineering" / "generated" / "pid.svg"
    if not f.exists():
        raise HTTPException(404, "run `engdata pid` first")
    return FileResponse(f, media_type="image/svg+xml")


@app.websocket("/api/v1/ws/live")
async def ws_live(ws: WebSocket) -> None:
    try:
        ws_user(ws)
    except HTTPException:
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            vals = await live_values()
            await ws.send_text(json.dumps(vals, default=str))
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        return

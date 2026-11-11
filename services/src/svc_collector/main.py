"""Level 3 collector: OPC UA subscription -> exception/swinging-door -> store-and-forward -> historian.

Conduit C1 (L3 -> L2): the collector is the OPC UA client; the DCS never initiates towards L3.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
from pathlib import Path
from typing import Any

import asyncpg
from asyncua import ua

from engdata.dataset import load
from plant.alarms import AlarmEngine
from svc_collector.buffer import Buffer
from svc_collector.swinging_door import Compressor
from svc_common import config
from svc_opcua.hmi import client as ua_client

log = logging.getLogger("collector")
UTC = dt.UTC


def _epoch(t: dt.datetime | None) -> float | None:
    if t is None:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.timestamp()


class Handler:
    def __init__(self, buf: Buffer, comps: dict[str, Compressor], names: dict[Any, str], store_raw: bool) -> None:
        self.buf, self.comps, self.names, self.store_raw = buf, comps, names, store_raw
        self.received = 0

    def datachange_notification(self, node: Any, val: Any, data: Any) -> None:
        name = self.names.get(node.nodeid)
        if name is None:
            return
        dv: ua.DataValue = data.monitored_item.Value
        ts = _epoch(dv.SourceTimestamp) or dt.datetime.now(UTC).timestamp()
        sts = _epoch(dv.ServerTimestamp)
        self.received += 1
        if name.startswith("ALM."):
            self.buf.put("alarm_event", ts, name[4:], 0.0, str(val), sts)
            return
        try:
            v = float(val)
        except (TypeError, ValueError):
            return
        q = dv.StatusCode.name if dv.StatusCode is not None else "Good"
        if self.store_raw:
            self.buf.put("sample_raw", ts, name, v, q, sts)
        comp = self.comps.get(name)
        points = comp.offer((ts, v, q)) if comp else [(ts, v, q)]
        for t, value, qual in points:
            self.buf.put("sample", t, name, value, qual, sts)


async def flusher(buf: Buffer) -> None:
    conn: asyncpg.Connection | None = None
    backoff = 1.0
    while True:
        try:
            if conn is None or conn.is_closed():
                conn = await asyncpg.connect(config.HISTORIAN_DSN, timeout=5)
                log.info("historian connected, buffer depth %d", buf.depth())
                backoff = 1.0
            rows = buf.peek(5000)
            if not rows:
                await asyncio.sleep(1.0)
                continue
            by_tbl: dict[str, list[tuple[Any, ...]]] = {}
            for _id, tbl, ts, tag, value, q, sts in rows:
                t = dt.datetime.fromtimestamp(ts, UTC)
                if tbl == "alarm_event":
                    by_tbl.setdefault(tbl, []).append((t, tag, q))
                else:
                    st = dt.datetime.fromtimestamp(sts, UTC) if sts else None
                    val = None if value is None or math.isnan(value) else value
                    by_tbl.setdefault(tbl, []).append((t, tag, val, q, st) if tbl == "sample" else (t, tag, val, q))
            async with conn.transaction():
                for tbl, recs in by_tbl.items():
                    if tbl == "sample":
                        sql = (
                            "INSERT INTO sample (ts, tag, value, quality, server_ts) VALUES ($1,$2,$3,$4,$5) "
                            "ON CONFLICT DO NOTHING"
                        )
                    elif tbl == "sample_raw":
                        sql = "INSERT INTO sample_raw (ts, tag, value, quality) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING"
                    else:
                        sql = "INSERT INTO alarm_event (ts, alarm, state) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING"
                    await conn.executemany(sql, recs)
            buf.ack(rows[-1][0])
        except (TimeoutError, OSError, asyncpg.PostgresError) as e:
            log.warning("historian unavailable (%s); buffering, depth %d", type(e).__name__, buf.depth())
            conn = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def register_tags(ds: Any) -> None:
    for _ in range(60):
        try:
            conn = await asyncpg.connect(config.HISTORIAN_DSN, timeout=5)
            break
        except (TimeoutError, OSError, asyncpg.PostgresError):
            await asyncio.sleep(2)
    else:
        return
    rows = []
    for t in ds.tags:
        span = t["range"][1] - t["range"][0]
        rows.append(
            (
                t["tag"],
                t["desc"],
                t["unit"]["symbol"],
                t["range"][0],
                t["range"][1],
                0.001 * span,
                0.0025 * span,
            )
        )
    await conn.executemany("INSERT INTO tag VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (tag) DO NOTHING", rows)
    await conn.close()


async def subscribe(buf: Buffer, ds: Any) -> None:
    comps = {
        t["tag"]: Compressor(exc_dev=0.001 * (t["range"][1] - t["range"][0]), comp_dev=0.0025 * (t["range"][1] - t["range"][0]))
        for t in ds.tags
    }
    store_raw = config.env("RGPF_STORE_RAW", "1") == "1"
    while True:
        try:
            c = await ua_client("collector")
            async with c:
                idx = await c.get_namespace_index("urn:rgpf:unit100")
                keys = [t["tag"] for t in ds.tags if t["class"] in ("instrument", "final_element")]
                keys += ["100-UY-2042", "100-FY-2001", "TRIP"]
                keys += [f"{t['tag']}.{a}" for t in ds.tags if t["class"] == "controller" for a in ("SP", "OUT")]
                nodes, names = [], {}
                for k in keys:
                    n = c.get_node(ua.NodeId(k, idx))
                    nodes.append(n)
                    names[n.nodeid] = k
                for a in AlarmEngine.from_dataset(ds.alarms).alarms:
                    n = c.get_node(ua.NodeId(f"ALM.{a.key}", idx))
                    nodes.append(n)
                    names[n.nodeid] = f"ALM.{a.key}"
                h = Handler(buf, comps, names, store_raw)
                sub = await c.create_subscription(1000, h)
                await sub.subscribe_data_change(nodes, queuesize=10)
                log.info("subscribed to %d nodes", len(nodes))
                while True:
                    await asyncio.sleep(10)
                    await c.check_connection()
                    log.info("received %d notifications, buffer depth %d", h.received, buf.depth())
        except Exception as e:  # reconnect on any client failure (server restart, partition)
            log.warning("OPC UA connection lost (%s: %s); retrying in 5 s", type(e).__name__, e)
            await asyncio.sleep(5)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("asyncua").setLevel(logging.ERROR)
    ds = load()
    buf = Buffer(Path(config.env("RGPF_BUFFER", "/data/collector/buffer.sqlite")))
    await register_tags(ds)
    await asyncio.gather(subscribe(buf, ds), flusher(buf))


if __name__ == "__main__":
    asyncio.run(main())

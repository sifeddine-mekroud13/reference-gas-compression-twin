"""Build the asset and context model (ADR 0008) from the engineering dataset.

Node kinds: enterprise, site, area, unit (ISA-95), equipment (functional location, ISO 14224
class, serial), tag, line, pid_item (DEXPI id), model3d (scene object), document.
"""

from __future__ import annotations

import json
import re
from typing import Any

import asyncpg

from engdata.dataset import Dataset


def _lt(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


async def build(conn: asyncpg.Connection, ds: Dataset) -> int:
    nodes: list[tuple[str, str, str, str | None, str]] = []
    edges: list[tuple[str, str, str]] = []
    f = ds.bod["facility"]
    chain = [("enterprise", f["enterprise"]), ("site", f["site"]), ("area", f["area"]), ("unit", f"Unit {f['unit']}")]
    path: list[str] = []
    prev = ""
    for kind, name in chain:
        path.append(_lt(name))
        nid = f"{kind}:{_lt(name)}"
        nodes.append((nid, kind, name, ".".join(path), "{}"))
        if prev:
            edges.append((prev, "has_part", nid))
        prev = nid
    unit_id, unit_path = prev, ".".join(path)
    layout = ds.layout["equipment"]
    for e in ds.equipment:
        eid = f"equipment:{e['tag']}"
        props = {
            "iso14224_class": e["iso14224_class"],
            "type": e["type"],
            "serial": e["serial"],
            "datasheet": e["datasheet"],
            "nozzles": e["nozzles"],
            "pos3d": layout[e["tag"]]["pos3d"],
        }
        nodes.append((eid, "equipment", e["tag"], f"{unit_path}.{_lt(e['tag'])}", json.dumps(props)))
        edges.append((f"equipment:{e['parent']}" if e["parent"] else unit_id, "has_part", eid))
        nodes.append(
            (
                f"pid_item:{e['tag']}",
                "pid_item",
                f"DEXPI {e['tag']}",
                None,
                json.dumps({"dexpi_id": f"EQ_{_lt(e['tag'])}", "xy": layout[e["tag"]]["pid"]}),
            )
        )
        nodes.append((f"model3d:{e['tag']}", "model3d", f"3D {e['tag']}", None, json.dumps({"object": e["tag"]})))
        nodes.append(
            (
                f"document:DS-{e['tag']}",
                "document",
                f"Datasheet {e['tag']}",
                None,
                json.dumps({"href": "engineering/data/equipment.yaml", "doc_type": "datasheet"}),
            )
        )
        edges += [
            (eid, "depicted_in", f"pid_item:{e['tag']}"),
            (eid, "rendered_as", f"model3d:{e['tag']}"),
            (eid, "documented_by", f"document:DS-{e['tag']}"),
        ]
    for ln in ds.lines["lines"]:
        lid = f"line:{ln['id']}"
        nodes.append((lid, "line", ln["id"], None, json.dumps(ln)))
        edges.append((unit_id, "has_part", lid))
        for end in (ln["from"], ln["to"]):
            kind, _, _ref = end.partition(":")
            if kind not in ("BL", "J"):
                edges.append((lid, "connected_to", f"equipment:{kind}"))
    for t in ds.tags:
        tid = f"tag:{t['tag']}"
        nodes.append(
            (
                tid,
                "tag",
                t["tag"],
                None,
                json.dumps({"class": t["class"], "desc": t["desc"], "unit": t["unit"]["symbol"], "range": t["range"]}),
            )
        )
        owner = f"equipment:{t['equipment']}" if t["equipment"] else f"line:{t['line']}"
        edges.append((owner, "measured_by", tid))
    async with conn.transaction():
        await conn.execute("DELETE FROM graph.edge")
        await conn.execute("DELETE FROM graph.node")
        await conn.executemany("INSERT INTO graph.node VALUES ($1,$2,$3,$4::ltree,$5::jsonb)", nodes)
        await conn.executemany("INSERT INTO graph.edge VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", edges)
    return len(nodes)


async def context(conn: asyncpg.Connection, node_id: str) -> dict[str, Any] | None:
    n = await conn.fetchrow("SELECT id, kind, name, path::text AS path, props FROM graph.node WHERE id=$1", node_id)
    if n is None:
        return None
    out = await conn.fetch(
        "SELECT e.rel, n.id, n.kind, n.name, n.props FROM graph.edge e JOIN graph.node n ON n.id = e.dst WHERE e.src=$1", node_id
    )
    inc = await conn.fetch(
        "SELECT e.rel, n.id, n.kind, n.name FROM graph.edge e JOIN graph.node n ON n.id = e.src WHERE e.dst=$1", node_id
    )
    # Recursive descent: everything below this node in the has_part tree
    sub = await conn.fetch(
        "WITH RECURSIVE t(id) AS (SELECT $1::text UNION SELECT e.dst FROM graph.edge e JOIN t ON e.src = t.id "
        "WHERE e.rel = 'has_part') SELECT n.id, n.kind, n.name FROM t JOIN graph.node n ON n.id = t.id",
        node_id,
    )
    return {
        "node": {**dict(n), "props": json.loads(n["props"])},
        "outgoing": [{**dict(r), "props": json.loads(r["props"])} for r in out],
        "incoming": [dict(r) for r in inc],
        "subtree": [dict(r) for r in sub],
    }

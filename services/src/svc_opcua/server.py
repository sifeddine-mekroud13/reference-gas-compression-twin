"""Emulated DCS OPC UA server (Level 2).

* Runs the plant simulator and control layer in real time (or accelerated, RGPF_SPEEDUP).
* Address space generated from the tag register, organized by the ISA-95 hierarchy
  (Enterprise / Site / Area / Unit / Equipment), equipment objects typed by ISO 14224 class.
* Security: only Basic256Sha256 SignAndEncrypt; no None endpoint; client application
  certificates must be in the trust list (allow-list), otherwise the secure channel is refused.
* Status codes from the sensor model are propagated (Good, Uncertain..., BadSensorFailure).
* Advisory nodes: the twin submits recommendations; only an operator decision applies them,
  and the DCS verifies each request against fixed bounds (NAMUR NOA NE 178 idea, ADR 0005).
  Control setpoints are never writable by clients.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
from pathlib import Path
from typing import Any

from asyncua import Server, ua
from asyncua.common.methods import uamethod
from asyncua.crypto.truststore import TrustStore
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions

from engdata.dataset import load
from plant.sim import Simulation
from svc_common import config
from svc_common.units import UNECE_NAMESPACE, unit_id

log = logging.getLogger("opcua")
NS_URI = "urn:rgpf:unit100"
ISO14224_TYPES = {
    "VE": "VesselType",
    "CO": "CompressorType",
    "EM": "ElectricMotorType",
    "HE": "HeatExchangerType",
    "VA": "ValveType",
}

# Advisory targets and the bounds the DCS enforces when applying an accepted advisory.
ADVISORY_BOUNDS: dict[str, tuple[float, float]] = {
    "100-PIC-2002.SP": (27.0, 31.0),  # bara
    "100-UIC-2030.SP": (12.0, 25.0),  # surge control line margin, %
    "100-TIC-3001.SP": (55.0, 65.0),  # degC
}


class Dcs:
    def __init__(self, sim: Simulation) -> None:
        self.sim = sim
        self.nodes: dict[str, Any] = {}
        self.adv: dict[str, Any] = {}
        self.audit: list[dict[str, Any]] = []

    def apply_setpoint(self, target: str, value: float) -> None:
        c = self.sim.ctrl
        if target == "100-PIC-2002.SP":
            c.pic.sp = value
        elif target == "100-UIC-2030.SP":
            c.asc.scl_margin = value
            c.asc.pid.sp = value
        elif target == "100-TIC-3001.SP":
            c.fans.sp = value


async def build(server: Server, dcs: Dcs) -> None:
    ds = load()
    idx = await server.register_namespace(NS_URI)
    base = server.nodes.base_object_type
    types = {}
    for code, name in ISO14224_TYPES.items():
        types[code] = await base.add_object_type(idx, name)
    objects = server.nodes.objects
    fac = ds.bod["facility"]
    ent = await objects.add_folder(idx, fac["enterprise"])
    site = await ent.add_folder(idx, fac["site"])
    area = await site.add_folder(idx, fac["area"])
    unit = await area.add_folder(idx, f"Unit {fac['unit']}")
    eq_nodes: dict[str, Any] = {}
    # parents first so children nest under them
    for e in sorted(ds.equipment, key=lambda e: e["parent"] is not None):
        parent = eq_nodes.get(e["parent"], unit)
        node = await parent.add_object(ua.NodeId(f"EQ.{e['tag']}", idx), e["tag"], types[e["iso14224_class"]])
        await node.add_property(idx, "Description", e["name"])
        await node.add_property(idx, "ISO14224Class", e["iso14224_class"])
        await node.add_property(idx, "SerialNumber", e["serial"])
        eq_nodes[e["tag"]] = node
    lines = await unit.add_folder(idx, "Lines")
    line_nodes: dict[str, Any] = {}
    for t in ds.tags:
        parent = eq_nodes.get(t["equipment"]) if t["equipment"] else None
        if parent is None:
            ln = t["line"]
            if ln not in line_nodes:
                line_nodes[ln] = await lines.add_object(idx, ln)
            parent = line_nodes[ln]
        if t["class"] in ("instrument", "final_element") or t["tag"] in ("100-UY-2042", "100-FY-2001"):
            var = await parent.add_variable(ua.NodeId(t["tag"], idx), t["tag"], 0.0, ua.VariantType.Double)
            await var.add_property(idx, "EURange", ua.Range(Low=t["range"][0], High=t["range"][1]))
            await var.add_property(
                idx,
                "EngineeringUnits",
                ua.EUInformation(
                    NamespaceUri=UNECE_NAMESPACE,
                    UnitId=unit_id(t["unit"]["code"]),
                    DisplayName=ua.LocalizedText(t["unit"]["symbol"]),
                    Description=ua.LocalizedText(t["desc"]),
                ),
            )
            await var.add_property(idx, "Description", t["desc"])
            dcs.nodes[t["tag"]] = var
        elif t["class"] == "controller":
            obj = await parent.add_object(ua.NodeId(t["tag"], idx), t["tag"])
            await obj.add_property(idx, "Description", t["desc"])
            for attr in ("SP", "OUT"):
                key = f"{t['tag']}.{attr}"
                dcs.nodes[key] = await obj.add_variable(ua.NodeId(key, idx), attr, 0.0, ua.VariantType.Double)
    sysf = await unit.add_folder(idx, "System")
    dcs.nodes["TRIP"] = await sysf.add_variable(ua.NodeId("TRIP", idx), "CompressorTripped", 0.0)
    dcs.nodes["TRIP_CAUSE"] = await sysf.add_variable(ua.NodeId("TRIP_CAUSE", idx), "TripCause", "")
    dcs.nodes["SIM_TIME"] = await sysf.add_variable(ua.NodeId("SIM_TIME", idx), "SimulationTime", 0.0)
    almf = await unit.add_folder(idx, "Alarms")
    for a in dcs.sim.alarms.alarms:
        dcs.nodes[f"ALM.{a.key}"] = await almf.add_variable(ua.NodeId(f"ALM.{a.key}", idx), a.key, "NORM")
    await _advisory(unit, idx, dcs)


async def _advisory(unit: Any, idx: int, dcs: Dcs) -> None:
    f = await unit.add_folder(ua.NodeId("Advisory", idx), "Advisory")
    for name, val in (
        ("Id", ""),
        ("TargetTag", ""),
        ("ProposedValue", 0.0),
        ("Rationale", ""),
        ("State", "NONE"),
        ("DecidedBy", ""),
        ("DecisionTime", ""),
        ("History", "[]"),
    ):
        dcs.adv[name] = await f.add_variable(ua.NodeId(f"ADV.{name}", idx), name, val)

    @uamethod
    async def submit(parent: Any, adv_id: str, target: str, value: float, rationale: str) -> str:
        if target not in ADVISORY_BOUNDS:
            return "REJECTED: target not on advisory allow-list"
        state = await dcs.adv["State"].read_value()
        if state == "PENDING":
            return "REJECTED: another advisory is pending"
        for k, v in (
            ("Id", adv_id),
            ("TargetTag", target),
            ("ProposedValue", float(value)),
            ("Rationale", rationale),
            ("State", "PENDING"),
            ("DecidedBy", ""),
            ("DecisionTime", ""),
        ):
            await dcs.adv[k].write_value(v)
        await _history(dcs, {"id": adv_id, "event": "SUBMITTED", "target": target, "value": value})
        return "PENDING"

    @uamethod
    async def decide(parent: Any, accept: bool, operator: str) -> str:
        if await dcs.adv["State"].read_value() != "PENDING":
            return "NO PENDING ADVISORY"
        if not operator:
            return "REJECTED: operator identity required"
        target = await dcs.adv["TargetTag"].read_value()
        value = await dcs.adv["ProposedValue"].read_value()
        lo, hi = ADVISORY_BOUNDS[target]
        if accept and not lo <= value <= hi:
            state = "BLOCKED"  # verification of request failed: DCS refuses
        elif accept:
            dcs.apply_setpoint(target, value)
            state = "ACCEPTED"
        else:
            state = "REJECTED"
        now = dt.datetime.now(dt.UTC).isoformat()
        await dcs.adv["State"].write_value(state)
        await dcs.adv["DecidedBy"].write_value(operator)
        await dcs.adv["DecisionTime"].write_value(now)
        await _history(dcs, {"id": await dcs.adv["Id"].read_value(), "event": state, "by": operator, "t": now})
        return state

    await f.add_method(
        idx,
        "Submit",
        submit,
        [ua.VariantType.String, ua.VariantType.String, ua.VariantType.Double, ua.VariantType.String],
        [ua.VariantType.String],
    )
    await f.add_method(idx, "Decide", decide, [ua.VariantType.Boolean, ua.VariantType.String], [ua.VariantType.String])


async def _history(dcs: Dcs, item: dict[str, Any]) -> None:
    dcs.audit.append(item)
    await dcs.adv["History"].write_value(json.dumps(dcs.audit[-50:]))


def _status(q: str) -> ua.StatusCode:
    return ua.StatusCode(getattr(ua.StatusCodes, q, ua.StatusCodes.Good))


async def publish(dcs: Dcs, epoch: dt.datetime) -> None:
    sim = dcs.sim
    # Real time: source time follows simulated time. Accelerated: the process runs faster than
    # the clock, so stamping with simulated time would put data in the future; use wall time.
    base = epoch + dt.timedelta(seconds=sim.t) if config.SPEEDUP == 1 else dt.datetime.now(dt.UTC)
    src_ts = base + dt.timedelta(seconds=config.CLOCK_SKEW_S)
    for key, (value, q) in sim.snapshot().items():
        node = dcs.nodes.get(key)
        if node is None:
            continue
        dv = ua.DataValue(
            Value=ua.Variant(float(value), ua.VariantType.Double),
            StatusCode=_status(q),
            SourceTimestamp=src_ts,
        )
        await node.write_value(dv)
    await dcs.nodes["TRIP_CAUSE"].write_value(sim.ctrl.trip_cause)
    await dcs.nodes["SIM_TIME"].write_value(float(sim.t))
    for a in sim.alarms.alarms:
        await dcs.nodes[f"ALM.{a.key}"].write_value(a.state)


async def make_server(pki: Path, endpoint: str) -> Server:
    server = Server()
    await server.init()
    server.set_endpoint(endpoint)
    server.set_server_name("RGPF Unit 100 emulated DCS")
    await server.set_application_uri("urn:rgpf:opcua-server")
    server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
    await server.load_certificate(str(pki / "opcua-server.der"))
    await server.load_private_key(str(pki / "opcua-server.pem"))
    trust = TrustStore([pki / "trusted"], [])
    await trust.load()
    server.set_certificate_validator(
        CertificateValidator(CertificateValidatorOptions.TRUSTED_VALIDATION | CertificateValidatorOptions.PEER_CLIENT, trust)
    )
    return server


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    sc = Path(config.SCENARIO) if config.SCENARIO else None
    sim = Simulation.from_scenario(sc) if sc else Simulation()
    dcs = Dcs(sim)
    server = await make_server(config.PKI, config.env("RGPF_OPCUA_ENDPOINT", "opc.tcp://0.0.0.0:4840/rgpf/"))
    await build(server, dcs)
    epoch = dt.datetime.now(dt.UTC)
    t_wall0 = time.monotonic()
    log.info("OPC UA server up, speedup %.1f, scenario %s", config.SPEEDUP, sc)
    async with server:
        next_pub = 0.0
        while True:
            target = (time.monotonic() - t_wall0) * config.SPEEDUP
            lag = target - sim.t
            if lag > 0:
                sim.advance(min(lag, 5.0))
            if sim.t >= next_pub:
                await publish(dcs, epoch)
                next_pub = sim.t + 1.0
            await asyncio.sleep(0.05)


if __name__ == "__main__":
    asyncio.run(main())

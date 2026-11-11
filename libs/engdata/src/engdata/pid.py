"""P&ID generation from the engineering dataset: DEXPI-style XML and an SVG rendering.

The XML follows the structure of DEXPI 1.3 / Proteus (PlantModel, Equipment with Nozzles,
PipingNetworkSystem with segments and connections, ProcessInstrumentationFunction). It is a
SUBSET and is not validated against the official DEXPI XSD; that check is listed in the
standards matrix. Layout coordinates are hand-authored (ADR 0011).
Every SVG element carries data-id = the asset-graph node id, for 3D / P&ID cross-linking.
"""

from __future__ import annotations

import datetime as dt
from xml.sax.saxutils import escape

from engdata.dataset import Dataset

DEXPI_CLASS = {
    "VE": "Vessel",
    "CO": "CentrifugalCompressor",
    "EM": "ElectricMotor",
    "HE": "AirCooledHeatExchanger",
    "VA": "Valve",
}


def _xy(ds: Dataset, end: str, jpos: dict[str, tuple[float, float]]) -> tuple[float, float]:
    kind, _, ref = end.partition(":")
    if kind == "J":
        return jpos[ref]
    if kind == "BL":
        return {"FEED": (40.0, 300.0), "EXPORT": (800.0, 450.0), "DRAIN": (60.0, 540.0)}[ref]
    x, y = ds.layout["equipment"][kind]["pid"]
    return float(x) + NOZZLE_OFFSET.get((kind, ref), (0, 0))[0], float(y) + NOZZLE_OFFSET.get((kind, ref), (0, 0))[1]


# Nozzle positions relative to the symbol centre (P&ID drawing convention, hand-authored).
NOZZLE_OFFSET = {
    ("100-V-101", "N1"): (-25, 0),
    ("100-V-101", "N2"): (0, -60),
    ("100-V-101", "N3"): (0, 60),
    ("100-K-101", "N1"): (-30, 0),
    ("100-K-101", "N2"): (30, -15),
    ("100-E-101", "N1"): (-80, 0),
    ("100-E-101", "N2"): (80, 0),
    ("100-FV-2030", "N1"): (12, 0),
    ("100-FV-2030", "N2"): (-12, 0),
    ("100-LV-1103", "N1"): (0, -8),
    ("100-LV-1103", "N2"): (-12, 0),
    ("100-NRV-2050", "N1"): (-12, 0),
    ("100-NRV-2050", "N2"): (12, 0),
}


def _junctions(ds: Dataset) -> dict[str, tuple[float, float]]:
    return {"J-01": (90.0, 300.0), "J-02": (640.0, 450.0)}


def dexpi_xml(ds: Dataset) -> str:
    eq = ds.equipment
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<PlantModel xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        f'  <PlantInformation SchemaVersion="4.1.1" OriginatingSystem="rgpf-engdata" '
        f'Date="{dt.date.today().isoformat()}" Units="mm" Discipline="PID" '
        f'Application="Reference Gas Processing Facility (fictional), Unit {ds.bod["facility"]["unit"]}"/>',
    ]
    for e in eq:
        out.append(
            f'  <Equipment ID="EQ_{e["tag"].replace("-", "_")}" ComponentClass="{DEXPI_CLASS[e["iso14224_class"]]}" '
            f'TagName="{e["tag"]}">'
        )
        out.append(
            f'    <GenericAttributes Set="DexpiAttributes"><GenericAttribute Name="Description" '
            f'Value="{escape(e["name"])}"/></GenericAttributes>'
        )
        for n in e["nozzles"]:
            out.append(
                f'    <Nozzle ID="NZ_{e["tag"].replace("-", "_")}_{n["id"]}" ComponentClass="Nozzle" '
                f'TagName="{n["id"]}"><GenericAttributes Set="DexpiAttributes"><GenericAttribute '
                f'Name="NominalDiameter" Value="DN{n["dn"]}"/></GenericAttributes></Nozzle>'
            )
        out.append("  </Equipment>")
    out.append('  <PipingNetworkSystem ID="PNS_100" ComponentClass="PipingNetworkSystem">')
    for ln in ds.lines["lines"]:

        def ref(end: str) -> str:
            kind, _, r = end.partition(":")
            if kind in ("J", "BL"):
                return f"{kind}_{r}".replace("-", "_")
            return f"NZ_{kind.replace('-', '_')}_{r}"

        out.append(
            f'    <PipingNetworkSegment ID="SEG_{ln["id"].replace("-", "_")}" ComponentClass="PipingNetworkSegment" '
            f'TagName="{ln["id"]}"><Connection FromID="{ref(ln["from"])}" ToID="{ref(ln["to"])}"/>'
            f'<GenericAttributes Set="DexpiAttributes"><GenericAttribute Name="NominalDiameter" '
            f'Value="DN{ln["dn"]}"/><GenericAttribute Name="FluidCode" Value="{ln["service"]}"/>'
            f"</GenericAttributes></PipingNetworkSegment>"
        )
    out.append("  </PipingNetworkSystem>")
    for t in ds.tags:
        if t["class"] in ("instrument", "controller"):
            out.append(
                f'  <ProcessInstrumentationFunction ID="PIF_{t["tag"].replace("-", "_")}" '
                f'ComponentClass="ProcessInstrumentationFunction" TagName="{t["tag"]}">'
                f'<GenericAttributes Set="DexpiAttributes"><GenericAttribute Name="Description" '
                f'Value="{escape(t["desc"])}"/></GenericAttributes></ProcessInstrumentationFunction>'
            )
    out.append("</PlantModel>")
    return "\n".join(out) + "\n"


def _symbol(e: dict[str, object], x: float, y: float) -> str:
    c = e["iso14224_class"]
    if c == "VE":
        return f'<rect x="{x - 25}" y="{y - 60}" width="50" height="120" rx="25" class="eq"/>'
    if c == "CO":
        return f'<polygon points="{x - 30},{y - 35} {x + 30},{y - 15} {x + 30},{y + 15} {x - 30},{y + 35}" class="eq"/>'
    if c == "EM":
        return (
            f'<circle cx="{x}" cy="{y}" r="{18 if e["type"] != "fan_motor" else 8}" class="eq"/>'
            f'<text x="{x}" y="{y + 4}" class="sym">M</text>'
        )
    if c == "HE":
        return f'<rect x="{x - 80}" y="{y - 25}" width="160" height="50" class="eq"/><path d="M{x - 70} {y} h140" class="thin"/>'
    if e["type"] == "check_valve":
        return (
            f'<polygon points="{x - 12},{y - 8} {x + 12},{y + 8} {x + 12},{y - 8} {x - 12},{y + 8}" class="eq"/>'
            f'<path d="M{x + 12} {y - 10} v20" class="eq"/>'
        )
    return f'<polygon points="{x - 12},{y - 8} {x + 12},{y + 8} {x + 12},{y - 8} {x - 12},{y + 8}" class="eq"/>'


def pid_svg(ds: Dataset) -> str:
    jpos = _junctions(ds)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 840 600" font-family="Arial, sans-serif">',
        "<style>.eq{fill:#e6e6e6;stroke:#333;stroke-width:1.5}.thin{stroke:#666;fill:none}"
        ".ln{stroke:#333;stroke-width:2;fill:none}.ln.hc{stroke-dasharray:6 3}"
        ".lbl{font-size:10px;fill:#222;text-anchor:middle}.sym{font-size:11px;text-anchor:middle;fill:#222}"
        ".inst{fill:#fff;stroke:#333}.itag{font-size:7px;text-anchor:middle;fill:#222}"
        "[data-id]{cursor:pointer}[data-id]:hover .eq{stroke:#1f5fbf;stroke-width:2.5}</style>",
        '<rect width="840" height="600" fill="#f2f2f2"/>',
    ]
    for ln in ds.lines["lines"]:
        (x1, y1), (x2, y2) = _xy(ds, ln["from"], jpos), _xy(ds, ln["to"], jpos)
        cls = "ln hc" if ln["service"] == "HC" else "ln"
        parts.append(
            f'<g data-id="line:{ln["id"]}"><path d="M{x1} {y1} H{(x1 + x2) / 2} V{y2} H{x2}" class="{cls}" fill="none"/>'
            f'<text x="{(x1 + x2) / 2 + 4}" y="{(y1 + y2) / 2 - 4}" class="lbl" text-anchor="start">{ln["id"]}</text></g>'
        )
    for e in ds.equipment:
        x, y = (float(v) for v in ds.layout["equipment"][e["tag"]]["pid"])
        label = e["tag"][-1] if e["type"] == "fan_motor" else e["tag"]
        ly = y + 75 if e["iso14224_class"] == "VE" else (y + 22 if e["type"] == "fan_motor" else y + 45)
        parts.append(f'<g data-id="equipment:{e["tag"]}">{_symbol(e, x, y)}<text x="{x}" y="{ly}" class="lbl">{label}</text></g>')
    per_eq: dict[str, int] = {}
    for t in ds.tags:
        if t["class"] not in ("instrument", "controller") or not t["equipment"]:
            continue
        x, y = (float(v) for v in ds.layout["equipment"][t["equipment"]]["pid"])
        k = per_eq.get(t["equipment"], 0)
        per_eq[t["equipment"]] = k + 1
        below = t["equipment"] in ("100-K-101", "100-KM-101")
        x0 = x - 60 if t["equipment"] != "100-KM-101" else x + 10
        ix = x0 + (k % 6) * 24
        iy = (y + 70 + (k // 6) * 24) if below else (y - 80 - (k // 6) * 24)
        letters, num = t["tag"].split("-")[1], t["tag"].split("-")[2]
        parts.append(
            f'<g data-id="tag:{t["tag"]}"><circle cx="{ix}" cy="{iy}" r="10" class="inst"/>'
            f'<text x="{ix}" y="{iy - 1}" class="itag">{letters}</text>'
            f'<text x="{ix}" y="{iy + 7}" class="itag">{num}</text></g>'
        )
    parts.append(
        '<text x="12" y="590" font-size="9" fill="#555">Generated from engineering/data. Simplified symbols, '
        "not ISO 10628 compliant. Fictional facility.</text></svg>"
    )
    return "\n".join(parts) + "\n"

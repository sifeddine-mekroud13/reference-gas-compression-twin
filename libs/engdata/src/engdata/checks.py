"""Cross-file consistency checks for the engineering dataset.

Errors fail CI. Warnings are reported but do not fail (e.g. alarm priority distribution,
which is guidance for a whole console, not a hard rule for a 17-alarm unit).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from engdata.dataset import Dataset

_TAG_RE = re.compile(r"^100-(?P<letters>[A-Z]+)-(?P<loop>\d{4})(?P<suffix>[A-Z]?)$")
_ORDER = {"LL": 0, "L": 1, "H": 2, "HH": 3}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _dupes(items: list[str]) -> list[str]:
    return [k for k, n in Counter(items).items() if n > 1]


def run_checks(ds: Dataset) -> Report:
    r = Report()
    eq = ds.equipment_by_tag()
    tags = ds.tags_by_name()
    line_ids = {ln["id"] for ln in ds.lines["lines"]}

    for d in _dupes([e["tag"] for e in ds.equipment]):
        r.errors.append(f"duplicate equipment tag {d}")
    for d in _dupes([t["tag"] for t in ds.tags]):
        r.errors.append(f"duplicate instrument tag {d}")
    for d in _dupes([ln["id"] for ln in ds.lines["lines"]]):
        r.errors.append(f"duplicate line {d}")

    # Feed composition
    total = sum(ds.bod["feed_gas"]["composition"].values())
    if abs(total - 1.0) > 1e-6:
        r.errors.append(f"feed composition sums to {total}")

    # Equipment hierarchy
    for e in ds.equipment:
        p = e["parent"]
        seen = {e["tag"]}
        while p is not None:
            if p not in eq:
                r.errors.append(f"{e['tag']}: parent {p} not in equipment list")
                break
            if p in seen:
                r.errors.append(f"{e['tag']}: cyclic parent chain")
                break
            seen.add(p)
            p = eq[p]["parent"]

    # Tags
    for t in ds.tags:
        name = t["tag"]
        m = _TAG_RE.match(name)
        letters = m["letters"] if m else ""
        if t["equipment"] is None and "line" not in t:
            r.errors.append(f"{name}: needs an equipment or a line")
        if t["equipment"] is not None and t["equipment"] not in eq:
            r.errors.append(f"{name}: equipment {t['equipment']} does not exist")
        if "line" in t and t["line"] not in line_ids:
            r.errors.append(f"{name}: line {t['line']} does not exist")
        lo, hi = t["range"]
        if not lo < hi:
            r.errors.append(f"{name}: range lo >= hi")
        if not lo <= t["nominal"] <= hi:
            r.errors.append(f"{name}: nominal {t['nominal']} outside range")
        cls = t["class"]
        if cls == "controller":
            if not letters.endswith("IC"):
                r.errors.append(f"{name}: controller tag must end in IC (ISA-5.1)")
            if t.get("pv") not in tags:
                r.errors.append(f"{name}: pv {t.get('pv')} is not a tag")
            out = t.get("output")
            if out is not None and out not in tags:
                r.errors.append(f"{name}: output {out} is not a tag")
        elif cls == "final_element":
            if not letters.endswith("V"):
                r.errors.append(f"{name}: final element tag must end in V")
            if name not in eq or eq[name]["iso14224_class"] != "VA":
                r.errors.append(f"{name}: final element must be a VA equipment item with same tag")
        elif cls == "calculated":
            if not letters.endswith("Y"):
                r.errors.append(f"{name}: calculated tag must use the Y (compute) function letter")
        elif cls == "instrument" and not letters.endswith("T"):
            r.errors.append(f"{name}: instrument tag must end in T (transmitter)")

    # Every equipment has 3D + P&ID placement, and no orphan layout entries
    placed = set(ds.layout["equipment"])
    for missing in sorted(set(eq) - placed):
        r.errors.append(f"{missing}: no 3D/P&ID placement in layout.yaml")
    for orphan in sorted(placed - set(eq)):
        r.errors.append(f"layout.yaml: orphan placement {orphan}")

    # Every top-level process equipment (not a sub-unit) carries at least one tag
    tagged = {t["equipment"] for t in ds.tags}
    for e in ds.equipment:
        if e["tag"] not in tagged and e["iso14224_class"] not in ("VA",):
            r.warnings.append(f"{e['tag']}: no instrument tags")

    # Line topology
    junctions = set(ds.lines["junctions"])
    bls = set(ds.lines["battery_limits"])
    nozzle_use: Counter[str] = Counter()
    junction_use: Counter[str] = Counter()
    bl_use: Counter[str] = Counter()
    for ln in ds.lines["lines"]:
        for end in (ln["from"], ln["to"]):
            kind, _, ref = end.partition(":")
            if kind == "BL":
                if ref not in bls:
                    r.errors.append(f"{ln['id']}: unknown battery limit {ref}")
                bl_use[ref] += 1
            elif kind == "J":
                if ref not in junctions:
                    r.errors.append(f"{ln['id']}: unknown junction {ref}")
                junction_use[ref] += 1
            else:
                nozzles = {n["id"] for n in eq.get(kind, {}).get("nozzles", [])}
                if kind not in eq:
                    r.errors.append(f"{ln['id']}: unknown equipment {kind}")
                elif ref not in nozzles:
                    r.errors.append(f"{ln['id']}: {kind} has no nozzle {ref}")
                nozzle_use[end] += 1
    for e in ds.equipment:
        for n in e["nozzles"]:
            key = f"{e['tag']}:{n['id']}"
            if nozzle_use[key] != 1:
                r.errors.append(f"nozzle {key} connected {nozzle_use[key]} times (expected 1)")
    for j in junctions:
        if junction_use[j] < 3:
            r.errors.append(f"junction {j} has {junction_use[j]} connections (expected >= 3)")
    for b in bls:
        if bl_use[b] != 1:
            r.errors.append(f"battery limit {b} used {bl_use[b]} times")

    # Alarms
    for a in ds.alarms:
        at = tags.get(a["tag"])
        if at is None:
            r.errors.append(f"alarm on unknown tag {a['tag']}")
            continue
        lo, hi = at["range"]
        if not lo <= a["setpoint"] <= hi:
            r.errors.append(f"alarm {a['tag']} {a['type']}: setpoint outside tag range")
        if a["type"] in ("H", "HH") and a["setpoint"] <= at["nominal"]:
            r.errors.append(f"alarm {a['tag']} {a['type']}: setpoint not above nominal")
        if a["type"] in ("L", "LL") and a["setpoint"] >= at["nominal"]:
            r.errors.append(f"alarm {a['tag']} {a['type']}: setpoint not below nominal")
    by_tag: dict[str, dict[str, float]] = {}
    for a in ds.alarms:
        if a["type"] in _ORDER:
            by_tag.setdefault(a["tag"], {})[a["type"]] = a["setpoint"]
    for tag_name, sps in by_tag.items():
        ordered = sorted(sps, key=_ORDER.__getitem__)
        values = [sps[k] for k in ordered]
        if values != sorted(values):
            r.errors.append(f"alarm {tag_name}: limits not ordered LL < L < H < HH")
    for d in _dupes([f"{a['tag']}/{a['type']}" for a in ds.alarms]):
        r.errors.append(f"duplicate alarm {d}")
    prio = Counter(a["priority"] for a in ds.alarms)
    n = len(ds.alarms)
    if n and prio[1] / n > 0.2:
        r.warnings.append(
            f"{prio[1]}/{n} alarms are priority 1; common guidance (EEMUA 191 / ISA-18.2 practice) "
            "is about 5 percent high, 15 percent medium, 80 percent low across a console"
        )
    return r

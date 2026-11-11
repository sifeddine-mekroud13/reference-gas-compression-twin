"""Engineering dataset tests: the real dataset passes, and each check catches its defect."""

import copy
import dataclasses

import pytest

from engdata.checks import run_checks
from engdata.dataset import Dataset, load
from engdata.sizing import run_sizing


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return load()


def test_dataset_is_consistent(ds: Dataset) -> None:
    rep = run_checks(ds)
    assert rep.ok, rep.errors


def test_sizing_passes(ds: Dataset) -> None:
    res = run_sizing(ds)
    assert res.ok, [c for c in res.checks if not c.passed]
    # Mass balance sanity: 4 MSm3/d of a 16.8 g/mol gas is about 33 kg/s.
    assert res.values["mass_flow_kg_s"] == pytest.approx(33.0, rel=0.02)


def _mutated(ds: Dataset, **changes: object) -> Dataset:
    return dataclasses.replace(copy.deepcopy(ds), **changes)  # type: ignore[arg-type]


def test_detects_orphan_tag(ds: Dataset) -> None:
    tags = copy.deepcopy(ds.tags)
    tags[0]["equipment"] = "100-V-999"
    assert any("does not exist" in e for e in run_checks(_mutated(ds, tags=tags)).errors)


def test_detects_missing_layout(ds: Dataset) -> None:
    layout = copy.deepcopy(ds.layout)
    del layout["equipment"]["100-K-101"]
    errs = run_checks(_mutated(ds, layout=layout)).errors
    assert any("100-K-101: no 3D/P&ID placement" in e for e in errs)


def test_detects_unconnected_nozzle(ds: Dataset) -> None:
    lines = copy.deepcopy(ds.lines)
    lines["lines"] = [ln for ln in lines["lines"] if ln["id"] != "100-L-003"]
    errs = run_checks(_mutated(ds, lines=lines)).errors
    assert any("100-V-101:N2 connected 0 times" in e for e in errs)


def test_detects_misordered_alarms(ds: Dataset) -> None:
    alarms = copy.deepcopy(ds.alarms)
    for a in alarms:
        if a["tag"] == "100-TT-2005" and a["type"] == "HH":
            a["setpoint"] = 140.0
    errs = run_checks(_mutated(ds, alarms=alarms)).errors
    assert any("not ordered" in e for e in errs)


def test_detects_bad_isa_letters(ds: Dataset) -> None:
    tags = copy.deepcopy(ds.tags)
    tags[0]["class"] = "controller"
    tags[0]["pv"] = tags[0]["tag"]
    errs = run_checks(_mutated(ds, tags=tags)).errors
    assert any("must end in IC" in e for e in errs)


def test_detects_undersized_scrubber(ds: Dataset) -> None:
    eq = copy.deepcopy(ds.equipment)
    eq[0]["datasheet"]["internal_diameter_m"] = 1.5
    assert not run_sizing(_mutated(ds, equipment=eq)).ok

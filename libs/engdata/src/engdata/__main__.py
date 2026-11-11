"""CLI: ``engdata check`` (schema + consistency) and ``engdata sizing [--write|--check]``."""

from __future__ import annotations

import argparse
import sys

from engdata.checks import run_checks
from engdata.dataset import REPO_ROOT, load
from engdata.sizing import render_markdown, run_sizing

SIZING_DOC = REPO_ROOT / "docs" / "sizing-calculations.md"


def main() -> int:
    ap = argparse.ArgumentParser(prog="engdata")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("pid", help="generate engineering/generated/pid.svg and dexpi.xml")
    sz = sub.add_parser("sizing")
    g = sz.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="regenerate docs/sizing-calculations.md")
    g.add_argument("--check", action="store_true", help="fail if the doc is stale")
    args = ap.parse_args()

    ds = load()
    if args.cmd == "check":
        rep = run_checks(ds)
        for w in rep.warnings:
            print(f"WARN  {w}")
        for e in rep.errors:
            print(f"ERROR {e}")
        print(
            f"{len(ds.tags)} tags, {len(ds.equipment)} equipment, "
            f"{len(ds.lines['lines'])} lines, {len(ds.alarms)} alarms: "
            f"{'OK' if rep.ok else 'FAILED'}"
        )
        return 0 if rep.ok else 1

    if args.cmd == "pid":
        from engdata.pid import dexpi_xml, pid_svg

        out = REPO_ROOT / "engineering" / "generated"
        out.mkdir(exist_ok=True)
        (out / "pid.svg").write_text(pid_svg(ds))
        (out / "dexpi.xml").write_text(dexpi_xml(ds))
        print(f"wrote {out / 'pid.svg'} and {out / 'dexpi.xml'}")
        return 0

    res = run_sizing(ds)
    md = render_markdown(res)
    for c in res.checks:
        print(
            f"{'PASS' if c.passed else 'FAIL'}  {c.item:16s} {c.quantity:32s} "
            f"req {c.required:10.4g}  prov {c.provided:10.4g} {c.unit}"
        )
    if args.write:
        SIZING_DOC.write_text(md)
    elif args.check and (not SIZING_DOC.exists() or SIZING_DOC.read_text() != md):
        print("docs/sizing-calculations.md is stale: run `engdata sizing --write`")
        return 1
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Seed the CMMS emulation: functional locations from the dataset plus a synthetic history.

Work orders are synthetic and coded in the ISO 14224 style (failure mode, mechanism,
maintenance activity). Codes as publicly summarized; verify against ISO 14224:2016 Annex B.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import asyncpg

from engdata.dataset import load
from svc_common import config

HISTORY = [
    # (days ago, location, type, mode, mechanism, cause, detection, activity, text, downtime_h)
    (
        700,
        "100-K-101",
        "preventive",
        None,
        None,
        None,
        "periodic maintenance",
        "7 service",
        "Annual inspection: borescope of first-stage impeller, light fouling observed",
        0,
    ),
    (
        540,
        "100-E-101",
        "corrective",
        "PDE",
        "5.2 contamination",
        "sand and dust on fins",
        "operator observation",
        "7 service",
        "High gas outlet temperature in summer, air-side fin cleaning",
        6,
    ),
    (
        420,
        "100-EM-101C",
        "corrective",
        "BRD",
        "2.4 wear",
        "bearing end of life",
        "condition monitoring",
        "1 replace",
        "Fan motor C bearing replaced after vibration increase",
        12,
    ),
    (
        365,
        "100-K-101",
        "condition_based",
        "LOO",
        "2.3 erosion / fouling",
        "process contamination",
        "condition monitoring",
        "7 service",
        "Offline wash, polytropic efficiency recovered 2.1 points",
        18,
    ),
    (
        250,
        "100-LV-1103",
        "corrective",
        "ERO",
        "1.6 sticking",
        "trim deposits",
        "operator observation",
        "2 repair",
        "Level valve sticking, trim cleaned and stroked",
        4,
    ),
    (
        120,
        "100-K-101",
        "corrective",
        "VIB",
        "1.3 clearance / alignment failure",
        "thermal growth",
        "condition monitoring",
        "4 adjust",
        "DE vibration alert, hot alignment check and correction",
        30,
    ),
    (
        30,
        "100-V-101",
        "preventive",
        None,
        None,
        None,
        "periodic maintenance",
        "9 inspection",
        "Demister pad inspection, no damage",
        0,
    ),
]


async def main() -> None:
    ds = load()
    for _ in range(60):
        try:
            conn = await asyncpg.connect(config.CMMS_DSN, timeout=5)
            break
        except (TimeoutError, OSError, asyncpg.PostgresError):
            await asyncio.sleep(2)
    else:
        raise SystemExit("CMMS database unavailable")
    await conn.executemany(
        "INSERT INTO functional_location VALUES ($1,$2,$3,$4) ON CONFLICT (tag) DO NOTHING",
        [(e["tag"], e["name"], e["iso14224_class"], e["serial"]) for e in ds.equipment],
    )
    serial = {e["tag"]: e["serial"] for e in ds.equipment}
    now = dt.datetime.now(dt.UTC)
    rows = []
    for i, (ago, loc, typ, mode, mech, cause, det, act, text, down) in enumerate(HISTORY):
        rep = now - dt.timedelta(days=ago)
        rows.append(
            (
                f"WO-{1000 + i}",
                loc,
                serial[loc],
                typ,
                mode,
                mech,
                cause,
                det,
                act,
                text,
                rep,
                rep + dt.timedelta(hours=max(down, 2)),
                float(down),
            )
        )
    await conn.executemany(
        "INSERT INTO work_order VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) ON CONFLICT (id) DO NOTHING", rows
    )
    await conn.close()
    print(f"CMMS seeded: {len(ds.equipment)} locations, {len(rows)} work orders")


if __name__ == "__main__":
    asyncio.run(main())

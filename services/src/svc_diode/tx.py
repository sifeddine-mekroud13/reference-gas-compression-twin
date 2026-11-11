"""Diode transmitter (Level 3 side). Emulates a hardware data diode (unidirectional gateway).

* Reads new historian, alarm, advisory and CMMS rows and pushes them over UDP only.
  No acknowledgement exists, so: every datagram carries a sequence number and is sent twice;
  reference tables (tags, advisories, work orders) are re-sent periodically (carousel), so
  the far side converges even after losses.
* The container firewall (infra/firewall/diode-tx.nft) allows only UDP to the receiver on the
  DMZ interface and drops all inbound traffic on it. Software emulation: a real diode enforces
  this in hardware (optical one-way link).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import socket
import zlib
from typing import Any

import asyncpg

from svc_common import config

log = logging.getLogger("diode-tx")
MAX_ROWS = 800


def _ser(v: Any) -> Any:
    return v.isoformat() if isinstance(v, dt.datetime) else v


class Tx:
    def __init__(self, host: str, port: int) -> None:
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0

    def send(self, kind: str, rows: list[dict[str, Any]]) -> None:
        for i in range(0, max(len(rows), 1), MAX_ROWS):
            self.seq += 1
            body = {"seq": self.seq, "kind": kind, "rows": [{k: _ser(v) for k, v in r.items()} for r in rows[i : i + MAX_ROWS]]}
            pkt = zlib.compress(json.dumps(body).encode())
            for _ in range(2):  # redundancy instead of retransmission
                try:
                    self.sock.sendto(pkt, self.addr)
                except OSError as e:
                    log.warning("send failed: %s", e)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    tx = Tx(config.env("RGPF_DIODE_RX_HOST", "diode-rx"), int(config.env("RGPF_DIODE_PORT", "5005")))
    wm_sample = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    wm_alarm = wm_sample
    n = 0
    while True:
        try:
            hist = await asyncpg.connect(config.HISTORIAN_DSN, timeout=5)
            cmms = await asyncpg.connect(config.CMMS_DSN, timeout=5)
            while True:
                rows = await hist.fetch(
                    "SELECT ts, tag, value, quality, ingest_ts FROM sample WHERE ingest_ts > $1 ORDER BY ingest_ts LIMIT 5000",
                    wm_sample,
                )
                if rows:
                    wm_sample = rows[-1]["ingest_ts"]
                    tx.send("sample", [dict(r) for r in rows])
                rows = await hist.fetch(
                    "SELECT ts, alarm, state, ingest_ts FROM alarm_event WHERE ingest_ts > $1 ORDER BY ingest_ts LIMIT 5000",
                    wm_alarm,
                )
                if rows:
                    wm_alarm = rows[-1]["ingest_ts"]
                    tx.send("alarm_event", [dict(r) for r in rows])
                if n % 15 == 0:  # carousel of reference data
                    tx.send("tag", [dict(r) for r in await hist.fetch("SELECT * FROM tag")])
                    tx.send("advisory", [dict(r) for r in await hist.fetch("SELECT * FROM advisory")])
                    tx.send("work_order", [dict(r) for r in await cmms.fetch("SELECT * FROM work_order")])
                n += 1
                await asyncio.sleep(2.0 if not rows else 0.2)
        except (TimeoutError, OSError, asyncpg.PostgresError) as e:
            log.warning("source unavailable: %s", e)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())

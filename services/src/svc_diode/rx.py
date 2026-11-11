"""Diode receiver (DMZ side): UDP in, replica database out. Never sends anything back."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import zlib
from collections import deque
from typing import Any

import asyncpg

from svc_common import config

log = logging.getLogger("diode-rx")

UPSERT = {
    "sample": (
        "INSERT INTO sample (ts, tag, value, quality) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
        ("ts", "tag", "value", "quality"),
    ),
    "alarm_event": (
        "INSERT INTO alarm_event (ts, alarm, state) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
        ("ts", "alarm", "state"),
    ),
    "tag": (
        "INSERT INTO tag VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (tag) DO NOTHING",
        ("tag", "description", "unit", "lo", "hi", "exc_dev", "comp_dev"),
    ),
    "advisory": (
        "INSERT INTO advisory VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (id) DO UPDATE SET "
        "state=EXCLUDED.state, decided_by=EXCLUDED.decided_by, decided_at=EXCLUDED.decided_at",
        ("id", "created", "target", "value", "rationale", "state", "decided_by", "decided_at"),
    ),
    "work_order": (
        "INSERT INTO work_order VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) ON CONFLICT (id) DO NOTHING",
        (
            "id",
            "functional_location",
            "serial",
            "wo_type",
            "failure_mode",
            "failure_mechanism",
            "failure_cause",
            "detection_method",
            "maintenance_activity",
            "description",
            "reported",
            "completed",
            "downtime_h",
        ),
    ),
}
TS_FIELDS = {"ts", "created", "decided_at", "reported", "completed"}


def _conv(k: str, v: Any) -> Any:
    return dt.datetime.fromisoformat(v) if k in TS_FIELDS and isinstance(v, str) else v


class Rx(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.q = queue
        self.seen: deque[int] = deque(maxlen=20000)
        self.seen_set: set[int] = set()
        self.last = 0
        self.stats = {"received": 0, "gaps": 0, "duplicates": 0}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            msg = json.loads(zlib.decompress(data))
        except (zlib.error, ValueError):
            return
        seq = int(msg["seq"])
        if seq in self.seen_set:
            self.stats["duplicates"] += 1
            return
        if len(self.seen) == self.seen.maxlen:
            self.seen_set.discard(self.seen[0])
        self.seen.append(seq)
        self.seen_set.add(seq)
        if seq < self.last - 10000:  # transmitter restarted: sequence reset
            self.last = 0
        if seq > self.last + 1 and self.last:
            self.stats["gaps"] += seq - self.last - 1
        self.last = max(self.last, seq)
        self.stats["received"] += 1
        self.q.put_nowait(msg)


async def writer(q: asyncio.Queue[dict[str, Any]], proto: Rx) -> None:
    conn: asyncpg.Connection | None = None
    while True:
        msg = await q.get()
        while True:
            try:
                if conn is None or conn.is_closed():
                    conn = await asyncpg.connect(config.REPLICA_DSN, timeout=5)
                sql, fields = UPSERT[msg["kind"]]
                await conn.executemany(sql, [tuple(_conv(f, r.get(f)) for f in fields) for r in msg["rows"]])
                s = proto.stats
                await conn.execute(
                    "INSERT INTO diode_status VALUES (1,$1,$2,$3,$4,now()) ON CONFLICT (id) DO UPDATE SET "
                    "last_seq=$1, received=$2, gaps=$3, duplicates=$4, updated=now()",
                    proto.last,
                    s["received"],
                    s["gaps"],
                    s["duplicates"],
                )
                break
            except (TimeoutError, OSError, asyncpg.PostgresError) as e:
                log.warning("replica unavailable: %s", e)
                conn = None
                await asyncio.sleep(3)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100000)
    loop = asyncio.get_running_loop()
    proto = Rx(q)
    await loop.create_datagram_endpoint(lambda: proto, local_addr=("0.0.0.0", int(config.env("RGPF_DIODE_PORT", "5005"))))
    log.info("diode receiver listening")
    await writer(q, proto)


if __name__ == "__main__":
    asyncio.run(main())

"""Store and forward: a historian outage loses no data (raw table)."""

from __future__ import annotations

import itertools
import time

from .conftest import compose, psql

TAG = "100-PT-2002"


def _gaps(since_epoch: float) -> tuple[int, float, float]:
    sql = f"select extract(epoch from ts) from sample_raw where tag='{TAG}' and ts > to_timestamp({since_epoch}) order by ts"
    rows = psql("historian", "historian", sql)
    ts = [float(x) for x in rows.splitlines() if x]
    gaps = sorted(b - a for a, b in itertools.pairwise(ts))
    return len(ts), gaps[len(gaps) // 2] if gaps else 0.0, gaps[-1] if gaps else 0.0


def test_historian_outage_no_data_loss() -> None:
    start = time.time()
    time.sleep(20)
    compose("stop", "historian")
    time.sleep(60)
    compose("start", "historian")
    deadline = time.time() + 180
    while time.time() < deadline:
        logs = compose("logs", "--since", "60s", "collector").stdout
        if "historian connected, buffer depth" in logs:
            break
        time.sleep(5)
    time.sleep(30)  # drain
    n, median, worst = _gaps(start)
    assert n > 20
    assert worst < 5 * median + 1.0, f"gap {worst:.1f} s vs median {median:.1f} s"

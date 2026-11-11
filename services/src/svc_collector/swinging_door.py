"""Exception and swinging-door compression, the data-reduction concept used by plant historians.

Exception test (at the interface): a value passes if it moved more than ExcDev from the last
passed value, if ExcMax seconds elapsed, or if the quality changed.
Swinging door (at the archive): a passed point is archived only when a straight line from the
last archived point can no longer stay within +/- CompDev of every point since.
Source: Bristol, E.H. (1990) "Swinging door trending: adaptive trend recording?", ISA
National Conference; public historian vendor documentation of ExcDev/CompDev.
Lossy by design. Note: because the archived point is the last raw point (not a point on the
feasible line), the classic algorithm does not strictly bound the error by CompDev; the test
measures it and asserts 2 x CompDev + ExcDev. Report the measured error, not the setting.
"""

from __future__ import annotations

from dataclasses import dataclass

Point = tuple[float, float, str]  # (t seconds, value, quality)


@dataclass
class Compressor:
    exc_dev: float
    comp_dev: float
    exc_max_s: float = 600.0
    comp_max_s: float = 3600.0
    _exc_last: Point | None = None
    _prev_raw: Point | None = None
    _prev_filtered: bool = False
    _archived: Point | None = None
    _snapshot: Point | None = None
    _hi: float = float("inf")
    _lo: float = float("-inf")

    def offer(self, p: Point) -> list[Point]:
        """Feed one raw point; return the points to archive (0, 1 or 2)."""
        last = self._exc_last
        if last is not None and p[2] == last[2] and abs(p[1] - last[1]) <= self.exc_dev and p[0] - last[0] < self.exc_max_s:
            return []
        self._exc_last = p
        return self._door(p)

    def _door(self, p: Point) -> list[Point]:
        a = self._archived
        if a is None:
            self._archived, self._snapshot = p, p
            self._hi, self._lo = float("inf"), float("-inf")
            return [p]
        out: list[Point] = []
        s = self._snapshot
        assert s is not None
        if p[2] != a[2] or not p[2].startswith("Good") or p[0] - a[0] >= self.comp_max_s:
            if s != a:
                out.append(s)
            out.append(p)
            self._archived, self._snapshot = p, p
            self._hi, self._lo = float("inf"), float("-inf")
            return out
        dt = p[0] - a[0]
        if dt <= 0:
            return out
        self._hi = min(self._hi, (p[1] + self.comp_dev - a[1]) / dt)
        self._lo = max(self._lo, (p[1] - self.comp_dev - a[1]) / dt)
        if self._lo > self._hi:
            out.append(s)
            self._archived = s
            dt2 = p[0] - s[0]
            self._hi = (p[1] + self.comp_dev - s[1]) / dt2
            self._lo = (p[1] - self.comp_dev - s[1]) / dt2
        self._snapshot = p
        return out

    def flush(self) -> list[Point]:
        """Archive the held snapshot (call at shutdown so the last value is not lost)."""
        s, a = self._snapshot, self._archived
        if s is not None and s != a:
            self._archived = s
            return [s]
        return []

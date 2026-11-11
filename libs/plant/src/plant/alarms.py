"""ISA-18.2 style alarm engine: deadband, on-delay, acknowledgement, shelving, flood metric.

States follow the ISA-18.2 alarm state model (simplified): NORM, UNACK (active, not
acknowledged), ACKED (active, acknowledged), RTNUN (returned to normal, not acknowledged),
SHLVD (shelved).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Alarm:
    tag: str
    kind: str
    setpoint: float
    priority: int
    deadband: float
    on_delay: float
    trip: bool = False
    state: str = "NORM"
    _timer: float = 0.0
    shelved_until: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.tag}.{self.kind}"

    def condition(self, v: float, active: bool) -> bool:
        hi = self.kind in ("H", "HH")
        if active:  # deadband applies on return to normal
            return v > self.setpoint - self.deadband if hi else v < self.setpoint + self.deadband
        return v > self.setpoint if hi else v < self.setpoint


@dataclass
class AlarmEngine:
    alarms: list[Alarm]
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=5000))
    _annunciations: deque[float] = field(default_factory=deque)

    @classmethod
    def from_dataset(cls, alarm_rows: list[dict[str, Any]]) -> AlarmEngine:
        return cls(
            [
                Alarm(
                    a["tag"],
                    a["type"],
                    a["setpoint"],
                    a["priority"],
                    a["deadband"],
                    a["on_delay_s"],
                    a.get("trip", False),
                )
                for a in alarm_rows
            ]
        )

    def update(self, values: dict[str, float], qualities: dict[str, str], t: float, dt: float) -> None:
        for a in self.alarms:
            v = values.get(a.tag)
            if v is None or qualities.get(a.tag, "Good").startswith("Bad"):
                continue  # bad-quality PVs raise a separate diagnostic, not a process alarm
            if a.state == "SHLVD":
                if t < a.shelved_until:
                    continue
                a.state = "NORM"
                self._event(t, a, "UNSHELVED")
            active = a.state in ("UNACK", "ACKED")
            cond = a.condition(v, active)
            if cond and not active:
                a._timer += dt
                if a._timer >= a.on_delay:
                    a.state = "UNACK"
                    self._annunciations.append(t)
                    self._event(t, a, "ACTIVE", v)
            elif not cond:
                a._timer = 0.0
                if a.state == "UNACK":
                    a.state = "RTNUN"
                    self._event(t, a, "RTN", v)
                elif a.state == "ACKED":
                    a.state = "NORM"
                    self._event(t, a, "RTN", v)

    def ack(self, key: str, t: float, user: str = "operator") -> bool:
        for a in self.alarms:
            if a.key == key:
                if a.state == "UNACK":
                    a.state = "ACKED"
                elif a.state == "RTNUN":
                    a.state = "NORM"
                else:
                    return False
                self._event(t, a, f"ACK by {user}")
                return True
        return False

    def shelve(self, key: str, t: float, duration_s: float) -> bool:
        for a in self.alarms:
            if a.key == key:
                a.state, a.shelved_until = "SHLVD", t + duration_s
                self._event(t, a, "SHELVED")
                return True
        return False

    def standing(self) -> list[Alarm]:
        return [a for a in self.alarms if a.state in ("UNACK", "ACKED", "RTNUN")]

    def rate_per_10min(self, t: float) -> int:
        """Annunciation count in the last 10 minutes (EEMUA 191 flood: > 10)."""
        while self._annunciations and self._annunciations[0] < t - 600:
            self._annunciations.popleft()
        return len(self._annunciations)

    def _event(self, t: float, a: Alarm, what: str, v: float | None = None) -> None:
        self.events.append({"t": t, "alarm": a.key, "priority": a.priority, "event": what, "value": v})

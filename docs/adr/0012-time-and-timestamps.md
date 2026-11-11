# 0012. Source timestamp is authoritative; clock skew is injected, not synchronised

- Status: accepted
- Date: 2026-11-09

## Context
OPC UA values carry SourceTimestamp (set by the device or DCS) and ServerTimestamp. Real
plants synchronise clocks with NTP or PTP (IEC 61588) and still see skew, steps and leap
handling issues. Running chrony inside containers is pointless: containers share the host
kernel clock and cannot discipline it without `SYS_TIME`.

## Decision
- The historian stores SourceTimestamp as `ts` and the collector receive time as
  `ingest_ts`. Every query, KPI and model uses `ts`.
- Late or out-of-order data is accepted (idempotent upsert on tag + ts) so the
  store-and-forward buffer can replay after an outage.
- Time faults are tested by injecting skew in the simulator source timestamps rather
  than by running time daemons.

## Consequences
- A device with a wrong clock produces wrongly placed data; `ingest_ts - ts` is retained
  so skew can be detected and alarmed (not yet implemented as an alarm).
- No PTP/NTP design is shown; a real project needs one (and IEC 62443 FR 6 audit logs
  depend on it).

# 0005. Twin compute at Level 3, read-only replica at Level 4, advisory write-back at L3

- Status: accepted
- Date: 2026-11-08

## Context
The original brief placed the twin at Level 4 behind a one-way data diode and also wrote
advisories back to Level 2 OPC UA nodes. Both cannot be true: a diode has no return path.

## Decision
- Calibration (state estimation), what-if engine and advisory generation run at **Level 3**
  (site operations), as on-premises optimization and APC do in practice.
- Advisories are written to dedicated OPC UA advisory nodes at Level 2 and need operator
  acknowledgement. The twin never writes control setpoints directly.
- Level 3.5 replicates one way to a Level 4 replica. Level 4 hosts the engineering UI,
  asset graph and API, and is strictly read-only towards the plant.
- Optional, off by default, simulation only: a bounded automatic write path modelled on the
  NAMUR Open Architecture concept (NE 175) with DCS-side verification of requests (NE 178):
  the emulated DCS accepts a twin request only within configured limits and rate limits.

## Consequences
Level 4 users see advisories and twin outputs through the replica, with replication latency.

## Alternatives
A reverse conduit from L4 with an allow-list: workable, but then the DMZ is a firewall
pair, not a diode, and must be described as such.

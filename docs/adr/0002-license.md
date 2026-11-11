# 0002. License: Apache-2.0

- Status: accepted
- Date: 2026-11-08

## Decision
Apache License 2.0 for all original code and documentation.

## Rationale
Explicit patent grant and patent retaliation clause, which matters in an industrial domain.
It is the dominant license in industrial open source (Eclipse IIoT projects use EPL or
Apache, OPC Foundation reference stacks are dual licensed, Kubernetes, Keycloak).

## Dependency compatibility (to keep current in `docs/dependency-licenses.md`)
| Dependency | License | Note |
|---|---|---|
| CoolProp | MIT | |
| numpy | BSD-3-Clause | |
| PyYAML | MIT | |
| jsonschema | MIT | |
| asyncua (M3) | LGPL-3.0 | Used unmodified as a dynamically imported dependency; compatible. Not vendored. |
| TimescaleDB (M4) | Apache-2.0 core, Timescale License (TSL) for compression and continuous aggregates | We use the official image and do not redistribute or offer it as a hosted DB service. Re-check TSL text before M4. |
| Keycloak (M6) | Apache-2.0 | |
| three.js, react-three-fiber (M7) | MIT | |

## Alternatives
MIT: simpler, no patent grant. GPL: discourages the industrial reuse this project is meant to show.

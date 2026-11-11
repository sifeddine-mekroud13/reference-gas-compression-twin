# Dependency licences

Project licence: Apache-2.0 (ADR 0002). Direct dependencies only; transitive licences should
be checked with a tool (`pip-licenses`, `license-checker`) before any redistribution. Not legal advice.

| Component | Use | Licence | Note |
|---|---|---|---|
| CoolProp | real-gas properties | MIT | |
| NumPy, SciPy | numerics | BSD-3-Clause | |
| scikit-learn | analytics | BSD-3-Clause | dev group only, not in images |
| PyYAML | dataset | MIT | |
| jsonschema | dataset schemas | MIT | |
| asyncua | OPC UA server and clients | LGPL-3.0 | Used unmodified as a library, dynamically imported. LGPL obligations apply if the image is redistributed (provide source or a way to relink). |
| cryptography | PKI, OPC UA security | Apache-2.0 or BSD | |
| FastAPI, Starlette, uvicorn | L4 API | MIT, BSD-3-Clause | |
| PyJWT | token validation | MIT | |
| asyncpg | Postgres client | Apache-2.0 | |
| httpx | JWKS fetch | BSD-3-Clause | |
| TimescaleDB 2.17 image | historian | Timescale License (TSL) for some features, Apache-2.0 core | Compression and policies used here are TSL community features: free to use, not to offer as a DBaaS |
| PostgreSQL 16 | replica | PostgreSQL License | |
| Keycloak 26 | identity provider | Apache-2.0 | |
| nftables | conduit filtering | GPL-2.0 | Debian package in the image, unmodified |
| React, react-dom | UI | MIT | |
| three.js, @react-three/fiber | 3D | MIT | |
| keycloak-js | UI login | Apache-2.0 | |
| Vite, TypeScript | build | MIT, Apache-2.0 | build time only |

Public datasets used by `analytics/benchmarks` keep their own licences (see datasets.toml);
CWRU and Paderborn data are research-use licences, not open data in the OSI sense.

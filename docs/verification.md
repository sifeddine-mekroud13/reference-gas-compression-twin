# Verification and validation report (M10)

Scope: what was measured on the reference machine, how, and what it does and does not show.
Verification here means "the software does what the design says". Validation (does the model
match a real compressor) is not possible without plant data: section 5 says what would be needed.

Reference machine: Linux 6.8, Docker 29.9, 32 GB RAM, Python 3.12, date 2026-11-09.

## 1. Unit and model tests (`uv run pytest`, 44 tests, all pass)

| Area | Check | Reference | Result |
|---|---|---|---|
| Thermo | methane density and Z at ISO 13443 conditions, nitrogen density, ideal-gas limit, PH/PS round trip | ISO 6976 table values, NIST WebBook | within test tolerances; multicomponent feed gas not checked against an independent tool (DWSIM cross-check open) |
| Sizing | polytropic head, power, discharge temperature at design | basis of design (165 kJ/kg, 6.9 MW, 134 degC) | reproduced, see docs/sizing-calculations.md |
| Simulator | steady state at design | 29/76 bara, about 9000 rpm, 134 degC, 33 kg/s | reproduced |
| Surge | export pressure step to 84 bara | anti-surge off: deep surge cycles; on: no surge | as expected |
| UKF | recovers injected degradation (head 0.96, efficiency 0.95) | injected values, with deliberate model mismatch (no inverse crime) | 0.966 and 0.951; cooler UA estimate wanders during fan staging (known gap) |
| OPC UA | trusted client connects; rogue CA and anonymous rejected | Basic256Sha256 SignAndEncrypt only | pass |
| Collector | swinging door error bound | classic SDT is not strictly bounded; test asserts 2 CompDev + ExcDev | pass |
| Diode receiver | gap and duplicate counting | synthetic sequences | pass |
| Analytics | PCA false alarm rate near alpha, correlation break detected, contribution points at the broken variable | synthetic correlated data | pass |

## 2. Integrated stack (`docker compose up`, `RGPF_STACK=1 uv run pytest tests/stack`)

| Check | Method | Result |
|---|---|---|
| Cold start | `docker compose down -v` then `up --wait` | all services healthy or running; CMMS seeded (11 locations, 7 work orders) |
| Twin loop | svc_twin log after start | steady state detected, UKF updated every 30 s cycle, polytropic efficiency KPI 79.9 to 80.2 percent |
| End-to-end data path | OPC UA to collector to historian to diode to L4 replica | data in replica within seconds; ingest latency (ingest_ts minus source ts) 0.9 s mean |
| Diode | sequence counters in `diode_status` | 0 gaps, every datagram received twice (duplicates = received) |
| Asset graph | replica `graph.node` and `graph.edge` | 107 nodes, 119 edges |
| C1 allowed | collector to opcua:4840 | open |
| C1 restricted | collector to opcua:22 and :5432 | blocked |
| L2 cannot initiate | opcua to collector and historian | blocked |
| L4 isolated | api to historian, opcua (by IP and by name) | blocked |
| DMZ one way | diode-rx to diode-tx (TCP 5005, 8000), diode-rx to historian | blocked |
| Host exposure | published ports and `ss -ltn` | only 127.0.0.1:8080 (Keycloak) and 127.0.0.1:8081 (UI); 4840, 5432, 5005 not listening on the host |
| Store and forward | historian stopped 60 s, restarted | buffer peaked at about 1700 rows, drained after reconnect; raw series for 100-PT-2002: median spacing 1.11 s, worst gap 2.24 s over the whole run, so no data lost |
| Authentication | no token, tampered signature, token from a non-allowed client | 401 in all cases |
| Authorisation | operator calls what-if, audit, degradation | 403 |
| What-if | engineer, design scenario | 200; 9051 rpm, 133.7 degC discharge |
| UI | `npm run build` (tsc strict plus Vite), nginx serves UI and proxies the API, CSP header present | pass; no automated browser tests, interactive behaviour not covered by this report |

## 3. Analytics

See docs/analytics-results.md (generated). Main points: PCA and the similarity model detect
fouling, bearing wear and a sensor drift in 4 to 8 minutes of compressed time with zero false
alarms on held-out healthy data; a stuck transmitter and a two-fan failure are essentially
invisible to them, which is the correct conclusion, not a tuning problem.

## 4. Defects found during V&V and fixed

- `nft flush ruleset` in the conduit containers also deleted Docker's embedded DNS NAT rules,
  so name resolution failed. Rulesets now replace only their own table.
- After dropping privileges, HOME still pointed at /root and the Postgres client failed on
  `/root/.postgresql`. The entry script now sets HOME.
- At speedup above 1, source timestamps followed simulated time and ran ahead of the clock
  (data stamped in the future). Accelerated runs now stamp wall time; real time runs keep
  simulated time.
- The twin never declared steady state on the live stack: the test compared raw min and max,
  and with about 1000 noisy samples per 5 minute window the noise extremes alone broke the
  1 percent flow band. Now compares segment means (unit tests cover noise and drift). After
  the fix the twin calibrates from the first cycle at the design point.
- The analytics workspace member was missing from the image, which broke `uv sync --locked`.

## 5. Not verified, or not verifiable here

- No validation against plant data. Map, efficiency, cooler and sensor models are plausible
  and literature based, not fitted to a real machine.
- DWSIM cross-check of the thermodynamics: listed in docs/sizing-calculations.md, still to be
  run by the owner.
- No load test beyond one simulated unit (about 60 tags at 1 Hz). The historian and diode
  have not been tested at site scale (tens of thousands of tags).
- No penetration test. The zone tests show the intended rules are in place; they do not show
  the absence of other paths (shared kernel, Docker daemon).
- The protective trips are machine protection logic in the simulator, not a SIS, and no
  IEC 61511 lifecycle work was done.
- Long run stability (days) not tested.

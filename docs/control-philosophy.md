# Control philosophy and process model, Unit 100

Implementation: `libs/plant` (simulator and emulated control layer). All equipment data comes
from `engineering/data` through `plant.params.from_dataset`; this page explains the modelling
choices and the control strategy.

## 1. Dynamic model (Greitzer compression system)

| State | Equation |
|---|---|
| Compressor mass flow | dm_c/dt = (A_c / L_c) (PR(m_c, N) p1 - p2) |
| Suction plenum pressure | dp1/dt = a1^2 / V1 (m_feed + m_rec - m_c) |
| Discharge plenum pressure | dp2/dt = a2^2 / V2 (m_c - m_rec - m_out) |
| Shaft speed | J domega/dt = tau_motor - P_shaft / omega |

Sources: Greitzer (1976) J. Eng. Power 98; Moore and Greitzer (1986); Gravdahl and Egeland (1999).

Parameters derived from the dataset (values printed by `plant.params.from_dataset().extras`):

| Quantity | Value | Basis |
|---|---|---|
| V2 discharge plenum | 8.2 m3 | lines 100-L-004/005/006/008 plus cooler tube volume from bare area (25.4 mm tubes) |
| V1 suction plenum | 28 m3 | scrubber gas space at NLL plus suction lines |
| L_c effective duct length | 4.4 m | 0.4 m per impeller plus 2 m nozzles. Modelling assumption, the least certain parameter |
| A_c | 0.126 m2 | DN400 suction nozzle |
| Helmholtz frequency | 25 rad/s | a2 sqrt(A_c / (V2 L_c)) |
| **Greitzer B** | **1.06** | U2 / (2 omega_H L_c). B above about 0.8 means deep surge (full flow reversal) is expected |

Numerics: the duct equation is stiff (the characteristic slope gives an eigenvalue near -4000 1/s),
so m_c is advanced with a linearly implicit Euler step; other states use explicit Euler at 2 ms.
Real-gas properties (Z, speed of sound, cooled gas density) are refreshed from `thermo_ref` every
10 s, never inside the ODE, so the model runs about 60 times faster than real time.

### Compressor characteristic (synthetic map)
Moore-Greitzer cubic in normalized flow, scaled with fan laws, fitted through the M1 design point
with a 10 percent head rise to the head peak at 70 percent of design flow. Reverse flow uses an
orifice-like parabola, beyond choke the curve is extended linearly. **Everything left of the peak
is extrapolated**: vendors do not test it.

Finding: because polytropic efficiency falls off-design, the pressure-ratio peak (where Greitzer
instability starts) lies at about 74 percent of design flow, to the right of the head peak. The
pressure-ratio curve is very flat near that peak (0.5 percent between 10 percent margin and the peak).

### Other subsystems
- Aftercooler: effectiveness-NTU, cross-flow both fluids unmixed (Incropera eq. 11.32), air-side UA
  scaling with air flow^0.6, 60 s thermal lag, natural draft of 8 percent when fans are off.
- Suction temperature: mixing of feed and cooled recycle, 20 s lag.
- Scrubber level: liquid inflow (mist plus scripted slugs) against the level valve (Cv form).
- Feed and export: battery-limit headers through quadratic resistances; export through the check valve.

## 2. Control strategy

| Loop | PV | MV | Type | Scan |
|---|---|---|---|---|
| 100-PIC-2002 | suction pressure | speed setpoint (cascade) | PI, direct | 100 ms |
| 100-SIC-2101 | shaft speed | motor torque (VSD) | PI | 50 ms |
| 100-UIC-2030 | surge margin (invariant coordinates) | recycle valve 100-FV-2030 | PI plus open-loop step | 50 ms |
| 100-LIC-1103 | scrubber level | 100-LV-1103 | PI | 100 ms |
| 100-TIC-3001 | cooler outlet temperature | number of fans running | staging with 2 K band, 60 s minimum interval | 100 ms |

### Anti-surge
- Coordinates: reduced flow q_r^2 = dp_o / p_s from the suction flow element 100-FT-2001, reduced head
  h_r = (PR^sigma - 1) / sigma. In the ideal-gas limit these are independent of gas composition and suction
  conditions, which is why industrial anti-surge controllers use them (public description in Batson (1996),
  "Invariant coordinate systems for compressor control", ASME 96-GT-240; verify).
- The surge limit line (SLL) is fitted at start-up from the map, as a vendor would supply it.
- Surge margin: (Q / Q_surge - 1) x 100 at the current reduced head.
- **Surge control line at 15 percent margin**, recycle trip line at 8 percent (open-loop step of 30 percent).
  Industry typically uses about 10 percent. Simulation showed 10 percent was not enough for this map: the flat
  pressure-ratio curve near the peak let normal pressure fluctuations push the operating point over the peak.
  This is a tuning result for a synthetic map, not a general recommendation.
- The valve fails open and fully opens on a trip.

### Machine protection (emulated, not a SIS)
Trips on 100-LT-1104 HH, 100-TT-2005 HH, 100-VT-2010X/2011X HH and 100-TT-2013 HH remove motor torque and open
the recycle valve. Latched until reset. Outside IEC 61511 scope; no SIL claim.

## 3. Verified behaviour (tests in `libs/plant/tests`)
- Design steady state reproduces M1: 29 / 76 bara, about 9000 rpm, 134 degC, 33 kg/s.
- Export pressure step to 84 bara: **deep surge with flow reversal and a high discharge temperature trip when
  anti-surge is disabled; no flow reversal with anti-surge active.**
- A stuck level valve plus a 3 m3 slug trips the compressor on 100-LT-1104 HH.
- 5 percent head and efficiency fouling raises discharge temperature by about 5 K and motor power by about 5 percent.

## 4. Known design gap found by simulation
On an emergency trip the compressor surges repeatedly during coast-down even with the recycle valve fully open
in 2 s: the cooled recycle loop (large V2, long loop) is too slow for the speed decay. This is the classic case
for a **hot-gas bypass** (a short, fast recycle from compressor discharge) or a faster, larger anti-surge valve.
Not fixed: it is kept as a documented finding and a what-if case for the twin.

## 5. Simplifications a reviewer should know
- One lumped suction and one lumped discharge plenum; no acoustic pipe dynamics.
- Ideal-polytropic pressure ratio relation with a real-gas Z refreshed slowly.
- No inlet guide vanes, no rotating stall model, no seal gas or lube oil system.
- Vibration is an overall-value model (1X scaled with speed squared, wear growth, broadband in surge); waveforms are
  synthesized separately for analytics.

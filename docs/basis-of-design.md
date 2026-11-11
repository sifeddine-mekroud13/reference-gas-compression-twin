# Basis of design, Unit 100

Data source: `engineering/data/basis_of_design.yaml`. Calculated values: [sizing-calculations.md](sizing-calculations.md) (generated).
The facility is fictional. No data from any real site is used.

## Process description
Lean natural gas from the inlet header (battery limit FEED, 30 bara, 40 degC) passes the suction
scrubber 100-V-101, is compressed by the VSD motor-driven centrifugal compressor 100-K-101 to
76 bara, cooled to 60 degC in the forced-draft air cooler 100-E-101, and leaves through the
discharge check valve 100-NRV-2050 to the export header (75 bara).

Anti-surge: cooled recycle. The recycle take-off is downstream of the aftercooler and upstream
of the check valve; the recycle valve 100-FV-2030 returns gas to the scrubber inlet. Consequences:

1. The scrubber sees full compressor flow including recycle, so it is sized at 1.2 x design flow.
2. The compressor discharge plenum (used by the surge model) includes discharge piping, the
   cooler and the recycle line up to the valve. A large plenum gives a large Greitzer B parameter
   and therefore deep surge. Fast valve stroking is required (fail open, 2 s stroke).
3. On a trip, cooled recycle has a long loop residence time. Many real trains add a hot-gas bypass
   for this case. Not modelled at this stage; flagged as a design gap for the control philosophy.

Capacity control: compressor speed (VSD). The suction pressure controller 100-PIC-2002 cascades
to the speed controller 100-SIC-2101. No suction throttle valve (energy loss).

## Design case
| Item | Value | Note |
|---|---|---|
| Flow | 4.0 MSm3/d (ISO 13443 reference conditions) | about 33 kg/s |
| Gas | AGA8 / ISO 12213-2 "Gulf Coast" reference gas, M about 16.8 g/mol | verify composition against official table |
| Suction | 29 bara, 40 degC | after scrubber and line losses |
| Discharge | 76 bara | pressure ratio 2.62 |
| Polytropic efficiency | 0.80 | design assumption for a 6-impeller between-bearing machine |
| Aftercooler outlet | 60 degC | 10 K approach at 50 degC ambient: tight, typical hot-climate design |
| Ambient | 50 degC dry bulb design, 0 degC minimum | hot desert case |
| Driver | 9.0 MW VSD induction motor | 1.10 x rated-point shaft power |

## Free liquids
The feed is far from its dew point at all conditions in the unit. Liquids at the scrubber come
from upstream carryover (mist, occasional condensate or water slugs) and are modelled as a
boundary disturbance, not computed by a flash.

## Key assumptions to verify
- Gulf Coast composition (AGA Report No. 8 / ISO 12213-2).
- Souders-Brown K = 0.107 m/s for a mesh pad and the GPSA pressure derating table.
- Air cooler bare-tube U = 450 W/m2K (GPSA Section 10 typical values).
- Motor margin of 110 percent (API 617 practice).

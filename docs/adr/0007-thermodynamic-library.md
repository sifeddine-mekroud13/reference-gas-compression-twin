# 0007. Thermodynamic property library

- Status: accepted
- Date: 2026-11-08

## Decision
- `libs/thermo` wraps CoolProp HEOS mixtures. For the GERG-2008 component set CoolProp
  uses the GERG-2008 (Kunz and Wagner 2012) pure-fluid and mixture model, so values should
  track ISO 20765-2 in the single-phase gas region. Gas phase is imposed; no flash.
- T solves for (p, h) and (p, s) use Newton on PT calls (about 0.3 ms each) instead of
  CoolProp's PS/PH flashes (about 25 ms each).
- The simulator (M2) will not call the EOS inside its ODE right-hand side. It uses property
  tables generated from this library, so it can run faster than real time.
- Cross-checks: published reference points in unit tests, and DWSIM for the design case
  (list in `docs/sizing-calculations.md`). Planned: compare against the NIST AGA8/GERG-2008
  reference code (usnistgov/AGA8) once its Python access path is confirmed.

## Not claimed
This is not a certified ISO 20765-2 implementation.

## Alternatives
`thermo` (Caleb Bell): broad, but GERG-2008 support was not confirmed. REFPROP: paid.

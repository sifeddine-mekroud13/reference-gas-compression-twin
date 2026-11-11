# 0006. Digital twin definition and claims

- Status: accepted
- Date: 2026-11-08

## Decision
- The project uses the ISO/IEC 30173 framing (a digital representation synchronized with
  its physical counterpart at a suitable rate) as the main claim. Verify wording against the
  standard.
- Against Kritzinger et al. (2018) we state the classification explicitly:
  - Automatic physical to digital flow (collector, historian, state estimation): yes.
  - Advisory with operator acknowledgement: manual digital to physical flow, so this mode is
    a **digital shadow** in Kritzinger's terms.
  - Only the optional bounded automatic write mode (ADR 0005) meets Kritzinger's digital
    twin definition, and only in simulation.
- The "physical asset" is a simulator. All documents say so.

## Consequences
No document or UI text claims "digital twin" without stating which definition and mode.

# 0011. P&ID and 3D layout coordinates are hand-authored data

- Status: accepted
- Date: 2026-11-08

## Decision
`engineering/data/layout.yaml` holds 3D placement and P&ID sheet coordinates; pipe routing
waypoints are added later. Generators (DEXPI XML, SVG, 3D scene) read them. Automatic P&ID
layout and automatic pipe routing are out of scope (open research problems).

## Consequences
CI checks that every equipment item has a placement and that no placement is orphaned.
Instrument bubbles are placed when the P&ID generator is built.

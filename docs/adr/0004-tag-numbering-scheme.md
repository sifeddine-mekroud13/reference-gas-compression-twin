# 0004. Tag numbering scheme

- Status: accepted
- Date: 2026-11-08

## Decision
Format: `<unit>-<letters>-<number><suffix>`.

- Unit: `100` (fictional export gas compression train).
- Equipment tags (company-style, not ISA-5.1): `V` vessel, `K` compressor, `KM` compressor
  driver motor, `E` exchanger, `EM` fan motor, `NRV` check valve, plus a 3-digit number,
  optional letter suffix for identical items (`100-EM-101A..D`).
- Instrument tags (ISA-5.1 functional letters): 4-digit loop number grouped by equipment:
  `11xx` scrubber, `20xx` compressor, `21xx` driver, `30xx` aftercooler, `40xx` export.
  Suffix letters for redundant or orthogonal sensors (`100-VT-2010X/Y`).
- Function classes enforced by `engdata check`: instrument ends in `T`, controller in `IC`,
  final element in `V` and is also an ISO 14224 `VA` equipment item with the same tag,
  calculated tags use the `Y` (compute) function letter.

## Tag vs equipment (functional location vs physical item)
A tag is a functional location. The physical item that fills it has a `serial`. Replacing a
motor keeps `100-KM-101` and changes the serial. This follows the CFIHOS and ISO 14224
distinction and is the basis of the asset model in M6.

## Consequences
Consistency rules are per tag class, not "every tag has a 3D object": controllers and
calculated tags have no physical representation.

## Sources
ISA-5.1 letter meanings from public summaries; verify against ISA-5.1-2022. NORSOK Z-DP-002
(freely available) used as a reference for coding structure.

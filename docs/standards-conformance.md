# Standards conformance matrix

"Designed in conformance with" means the design follows publicly available descriptions of the
standard. Nothing here is certified. Column "Verify" lists what needs checking against the
official text.

| Area | Standard | Where applied | Status | Verify |
|---|---|---|---|---|
| DT framework | ISO/IEC 30173, ISO 23247 | ADR 0006 | Framing chosen | Exact definition wording |
| DT classification | Kritzinger et al. 2018 | ADR 0006 | Applied | Open paper |
| Hierarchy | ISA-95 / IEC 62264 | `basis_of_design.yaml` facility block, asset model (M6) | Partial | Equipment hierarchy levels |
| Tag naming | ISA-5.1 | ADR 0004, `engdata check` | Applied | Letter tables |
| Equipment taxonomy | ISO 14224 | `equipment.yaml` classes, CMMS (M4) | Partial | Class codes (Table A.4) |
| Handover data | CFIHOS, ISO 15926 concepts | Tag vs physical item split | Partial | CFIHOS RDL classes |
| P&ID exchange | DEXPI | Planned | Not started | Schema version |
| Compressors | API 617 / ISO 10439 | Datasheet, driver margin, vibration limits | Partial | Driver margin clause, vibration acceptance formula |
| Performance | ASME PTC 10 (Schultz method) | `machinery.compressor.schultz` | Implemented, tested vs multi-step | Full PTC 10 procedure |
| Equation of state | GERG-2008 / ISO 20765-2 | ADR 0007 | Via CoolProp, not certified | Reference test values |
| Air coolers | API 661 | Datasheet structure | Referenced | Thermal and mechanical requirements |
| Machinery protection | API 670, ISO 20816 | Vibration tags and alarms | Partial | Alert/danger setting practice |
| Condition monitoring | ISO 13374, ISO 17359, MIMOSA OSA-CBM | Analytics milestone | Not started | |
| Alarm management | ISA-18.2 / IEC 62682, EEMUA 191 | `alarms.yaml`, alarm philosophy | Partial | Metrics definitions |
| Instrument diagnostics | NAMUR NE 107, NE 43 | Sensor model (M2) | Planned | |
| Monitoring and optimization write path | NAMUR NOA NE 175 / NE 178 | ADR 0005 | Planned | |
| HMI | ISA-101 | 2D overview displays only, not the 3D view | Planned | |
| Connectivity | IEC 62541 (OPC UA), companion specs (PA-DIM OPC 30081, Machinery OPC 40001) | M3 | Planned | |
| Cybersecurity | IEC 62443-3-2, 3-3 | ADR 0010, security milestone | Planned | FR/SR table |
| Asset management | ISO 55000 | Context only | Referenced | |
| Units | UNECE Rec. 20 codes (OPC UA EUInformation) | `tags.yaml` | Applied | Codes B54 (kJ/kg) and A94 (g/mol) unverified |

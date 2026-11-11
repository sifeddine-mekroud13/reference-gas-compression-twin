# Alarm philosophy (summary)

Lifecycle per ISA-18.2 / IEC 62682: philosophy, identification, rationalization, design,
implementation, operation, monitoring, management of change. The alarm list in
`engineering/data/alarms.yaml` is the output of rationalization: every alarm has a consequence,
an operator action and a maximum response time. An alarm without an operator action is not an alarm.

## Priority
| Priority | Meaning | Max response time |
|---|---|---|
| 1 (high) | Imminent trip or equipment damage | 5 min or less |
| 2 (medium) | Degradation needing action this shift segment | 10 to 30 min |
| 3 (low) | Attention, planning | 30 min or more |

Target distribution across a console (EEMUA 191 and ISA-18.2 practice): about 5 / 15 / 80 percent.
This unit has a high share of priority 1 alarms because most of its alarms precede trips. The
consistency check reports this as a warning, not an error.

## Design rules
- Deadbands and on-delays on every alarm (values in the alarm list).
- Trips (`trip: true`) belong to the emulated machine protection layer, not a SIS. No IEC 61511 claim.
- Shelving, suppression by design (e.g. low-flow alarms suppressed when the compressor is stopped)
  and flood metrics are implemented in the control layer (M2).
- Performance targets (EEMUA 191): average below 1 alarm per 10 min per operator in steady state;
  flood defined as more than 10 alarms in 10 min.

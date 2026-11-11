# Architecture: zones and data flow (C4 container view, simplified)

```mermaid
flowchart LR
  subgraph L01["Level 0/1: simulated process"]
    SIM[Plant simulator<br/>Greitzer compressor, scrubber, cooler,<br/>sensor model, fault injection]
  end
  subgraph L2["Level 1/2: emulated control"]
    CTRL[Control layer<br/>PID, anti-surge, trips, ISA-18.2 alarms]
    OPC[OPC UA server<br/>SignAndEncrypt, advisory nodes]
  end
  subgraph L3["Level 3: site operations"]
    COL[Collector<br/>swinging door, store-and-forward]
    HIS[(Historian<br/>TimescaleDB)]
    CMMS[(CMMS emulation)]
    TWIN[Twin services<br/>calc, UKF, what-if, advisory]
  end
  subgraph L35["Level 3.5: DMZ"]
    DIO[Diode emulation<br/>one-way replication]
  end
  subgraph L4["Level 4: engineering platform (read-only)"]
    REP[(Replica historian)]
    GRAPH[(Asset graph)]
    API[API<br/>OIDC, RBAC, audit]
    UI[Web UI<br/>3D, P&ID, KPIs]
  end
  SIM <--> CTRL --> OPC
  OPC -- subscription --> COL --> HIS
  HIS --> TWIN
  TWIN -- advisory write --> OPC
  HIS --> DIO
  TWIN --> DIO
  CMMS --> DIO
  DIO -- one way --> REP
  REP --> API
  GRAPH --> API --> UI
```

The advisory write from L3 to L2 is the only path towards control, and it never targets
control setpoints (ADR 0005). Level 4 has no path towards Level 3 or below.

-- CMMS emulation (in reality SAP PM or Maximo). Separate database on the same server to save
-- resources in the demo; in a plant it is a separate system in the Level 3 / business zone.
CREATE DATABASE cmms OWNER rgpf;
\connect cmms
CREATE TABLE IF NOT EXISTS functional_location (
  tag text PRIMARY KEY,
  description text NOT NULL,
  iso14224_class text NOT NULL,
  installed_serial text NOT NULL
);
-- Codes per ISO 14224:2016 Annex B tables as publicly summarized (verify against the standard).
CREATE TABLE IF NOT EXISTS work_order (
  id text PRIMARY KEY,
  functional_location text NOT NULL REFERENCES functional_location(tag),
  serial text NOT NULL,
  wo_type text NOT NULL CHECK (wo_type IN ('corrective', 'preventive', 'condition_based')),
  failure_mode text,          -- e.g. VIB, OHE, PDE, LOO, ELP (Table B.6 style codes)
  failure_mechanism text,     -- e.g. 1.2 vibration, 2.4 wear, 2.7 overheating
  failure_cause text,
  detection_method text,      -- e.g. condition monitoring, periodic maintenance, operator observation
  maintenance_activity text,  -- e.g. 1 replace, 2 repair, 4 adjust, 7 service, 9 inspection, 10 overhaul
  description text NOT NULL,
  reported timestamptz NOT NULL,
  completed timestamptz,
  downtime_h double precision DEFAULT 0
);

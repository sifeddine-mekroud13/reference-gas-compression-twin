-- Level 4 replica (plain PostgreSQL). Written only by the diode receiver; read by the API.
CREATE TABLE IF NOT EXISTS tag (tag text PRIMARY KEY, description text, unit text, lo double precision,
  hi double precision, exc_dev double precision, comp_dev double precision);
CREATE TABLE IF NOT EXISTS sample (ts timestamptz NOT NULL, tag text NOT NULL, value double precision,
  quality text NOT NULL, PRIMARY KEY (tag, ts));
CREATE INDEX IF NOT EXISTS sample_ts ON sample (ts DESC);
CREATE TABLE IF NOT EXISTS alarm_event (ts timestamptz NOT NULL, alarm text NOT NULL, state text NOT NULL,
  PRIMARY KEY (alarm, ts));
CREATE TABLE IF NOT EXISTS advisory (id text PRIMARY KEY, created timestamptz, target text, value double precision,
  rationale text, state text, decided_by text, decided_at timestamptz);
CREATE TABLE IF NOT EXISTS work_order (id text PRIMARY KEY, functional_location text, serial text, wo_type text,
  failure_mode text, failure_mechanism text, failure_cause text, detection_method text, maintenance_activity text,
  description text, reported timestamptz, completed timestamptz, downtime_h double precision);
CREATE TABLE IF NOT EXISTS diode_status (id int PRIMARY KEY DEFAULT 1, last_seq bigint, received bigint,
  gaps bigint, duplicates bigint, updated timestamptz);

-- Asset and context model (ADR 0008): typed nodes, ltree hierarchy, typed edges.
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE SCHEMA IF NOT EXISTS graph;
CREATE TABLE IF NOT EXISTS graph.node (
  id text PRIMARY KEY,
  kind text NOT NULL,         -- enterprise, site, area, unit, equipment, tag, line, document, pid_item, model3d
  name text NOT NULL,
  path ltree,                 -- ISA-95 hierarchy path for hierarchy nodes
  props jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS node_path ON graph.node USING gist (path);
CREATE TABLE IF NOT EXISTS graph.edge (
  src text NOT NULL REFERENCES graph.node(id),
  rel text NOT NULL,          -- has_part, measured_by, connected_to, depicted_in, rendered_as, documented_by
  dst text NOT NULL REFERENCES graph.node(id),
  PRIMARY KEY (src, rel, dst)
);

-- Audit log (API): every request on sensitive resources and every what-if run.
CREATE TABLE IF NOT EXISTS audit_log (id bigserial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(),
  subject text, username text, roles text[], method text, path text, status int, detail jsonb);

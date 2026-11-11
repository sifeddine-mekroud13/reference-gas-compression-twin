-- Level 3 historian (TimescaleDB). Source timestamp is authoritative (docs/adr/0012).
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS tag (
  tag text PRIMARY KEY,
  description text NOT NULL,
  unit text NOT NULL,
  lo double precision NOT NULL,
  hi double precision NOT NULL,
  exc_dev double precision NOT NULL,
  comp_dev double precision NOT NULL
);

-- Compressed (swinging door) archive: what the historian keeps.
CREATE TABLE IF NOT EXISTS sample (
  ts timestamptz NOT NULL,          -- OPC UA SourceTimestamp
  tag text NOT NULL,
  value double precision,
  quality text NOT NULL,            -- OPC UA StatusCode symbolic name
  server_ts timestamptz,            -- OPC UA ServerTimestamp (diagnostics only)
  ingest_ts timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tag, ts)
);
SELECT create_hypertable('sample', 'ts', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

-- Raw stream kept briefly for V&V of the compression (compression ratio, reconstruction error).
CREATE TABLE IF NOT EXISTS sample_raw (
  ts timestamptz NOT NULL,
  tag text NOT NULL,
  value double precision,
  quality text NOT NULL,
  PRIMARY KEY (tag, ts)
);
SELECT create_hypertable('sample_raw', 'ts', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 hour');
SELECT add_retention_policy('sample_raw', INTERVAL '2 days', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS alarm_event (
  ts timestamptz NOT NULL,
  alarm text NOT NULL,
  state text NOT NULL,
  ingest_ts timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (alarm, ts)
);

-- Twin outputs computed at Level 3 (KPIs, estimates, advisories) are stored as samples with
-- tag names prefixed "TWIN." plus this table for advisory records.
CREATE TABLE IF NOT EXISTS advisory (
  id text PRIMARY KEY,
  created timestamptz NOT NULL DEFAULT now(),
  target text NOT NULL,
  value double precision NOT NULL,
  rationale text NOT NULL,
  state text NOT NULL,
  decided_by text,
  decided_at timestamptz
);

-- Native columnar compression after 7 days (Timescale License feature, see ADR 0002).
ALTER TABLE sample SET (timescaledb.compress, timescaledb.compress_segmentby = 'tag');
SELECT add_compression_policy('sample', INTERVAL '7 days', if_not_exists => TRUE);

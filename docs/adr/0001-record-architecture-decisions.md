# 0001. Record architecture decisions

- Status: accepted
- Date: 2026-11-08

## Context
Decisions that are expensive to reverse must be traceable for reviewers and for the talk.

## Decision
Use lightweight ADRs in MADR style under `docs/adr/`, numbered, one decision per file, never
edited after acceptance except to mark them superseded.

## Consequences
Every significant change of direction produces a new ADR that supersedes the old one.

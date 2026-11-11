# 0008. Asset and context model storage: PostgreSQL, relational

- Status: proposed (implemented in M6)
- Date: 2026-11-08

## Decision
A dedicated PostgreSQL instance at Level 4 (not the historian's database, which is Level 3).
Nodes in typed tables (site, area, unit, functional location, physical item, document,
3D object, P&ID item, work order), hierarchy with `ltree`, other relations in a typed edge
table, traversal with recursive CTEs. Apache AGE only if Cypher queries prove necessary.

## Rationale
One database technology, no GPL Neo4j Community licensing, mature tooling, and the graph is
small (hundreds to thousands of nodes).

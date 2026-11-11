# Zones and conduits

Designed with reference to IEC 62443-3-2 (zone and conduit partitioning) and IEC 62443-3-3
(system requirements). This is a teaching implementation on one Docker host, not an
assessed system: no security level (SL) is claimed. Target SL notes below say what each
control is trying to show.

## Zones

| Zone | Purdue | Network | Members | Notes |
|---|---|---|---|---|
| Z1 Control | L1/L2 | l2 10.10.2.0/24 (internal) | opcua (simulator, control, OPC UA server) | Emulated DCS. No outbound paths. |
| Z2 Operations | L3 | l3 10.10.3.0/24 (internal) | historian, cmms-seed, collector, twin, diode-tx | Site level. Twin runs here (ADR 0005). |
| Z3 DMZ | L3.5 | dmz 10.10.35.0/24 (internal) | diode-tx, diode-rx | Only one-way UDP. |
| Z4 Enterprise | L4 | l4 10.10.4.0/24 (not internal: needed for host ports) | diode-rx, replica, keycloak, api, ui | Read-only copy of plant data. Only zone with host ports (127.0.0.1). |

## Conduits

| Id | From | To | Protocol | Enforcement |
|---|---|---|---|---|
| C1 | collector, twin (L3) | opcua 10.10.2.10 (L2) | OPC UA TCP 4840, Basic256Sha256 SignAndEncrypt, X.509 allow-list | `conduit-l3-l2.nft` on the client: only 4840 to .10 may be initiated; L2 can initiate nothing. Server rejects unsecured and untrusted clients (tested). |
| C2 | diode-tx (L3) | diode-rx 10.10.35.20 (DMZ) | UDP 5005, one way | `diode-tx.nft`: output UDP 5005 only, all DMZ input dropped. `diode-rx.nft`: input UDP 5005 only, all DMZ output dropped. No TCP, no ACKs; loss handled by duplication and carousel. |
| C3 | browser (host) | ui, keycloak (L4) | HTTP on 127.0.0.1 | Ports bound to loopback. TLS not configured (demo). |

Advisory write-back (ADR 0005): the twin writes to advisory nodes on the OPC UA server over C1.
The DCS side decides; nothing in L4 can write to the plant because no conduit from L4 leaves
the zone.

## IEC 62443-3-3 foundational requirements

| FR | What is implemented | Gap versus a real system |
|---|---|---|
| FR1 Identification and authentication | OPC UA application certificates per service, allow-list trust store; OIDC (Keycloak) with RS256 JWT, issuer, audience/azp checks at the API | No hardware-backed keys, no MFA, Keycloak in dev mode, demo users |
| FR2 Use control | Roles operator, process_engineer, maintenance, admin; what-if only for process_engineer; advisory decisions only via the DCS method | No separation of duties review, no break-glass account procedure |
| FR3 System integrity | Signed and encrypted OPC UA; NOA-style bounds check on advisory values; image built from a locked dependency set | No image signing, no SBOM attestation, no secure boot |
| FR4 Data confidentiality | SignAndEncrypt on C1; secrets only in `.env` (gitignored) | Diode and L4 HTTP are plaintext; database passwords in environment variables |
| FR5 Restricted data flow | Internal networks, one-way UDP diode, host nftables on conduit endpoints | Host-based, not an appliance; a root compromise of a conduit endpoint can remove the rules |
| FR6 Timely response to events | API audit log (who, what, when); diode sequence gap counters; alarm engine | No SIEM, no central log store, no time synchronisation design (ADR 0012) |
| FR7 Resource availability | Store-and-forward buffer in the collector; restart policies; diode carousel resends reference data | Single host, no redundancy, no DoS protection |

## Known weaknesses (honest list)

- Everything shares one kernel. Container isolation is not zone isolation in the 62443 sense.
- The collector and twin are dual-homed L3/L2 hosts. In a plant they would sit behind a
  firewall with only C1 allowed; here host nftables stands in for that firewall.
- `pki-init` and the conduit entry scripts start as root (to write the volume and load
  nftables); applications then run as uid 10001.
- Keycloak `start-dev` uses HTTP and a local H2 store.

## Verification

Run against a live stack: `RGPF_STACK=1 uv run pytest tests/stack`. See docs/verification.md
for the results recorded on the reference machine.

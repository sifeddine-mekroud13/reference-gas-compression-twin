# 0010. Zone and conduit enforcement: internal Docker networks plus per-host nftables

- Status: accepted (revised during the security milestone; supersedes the router-container draft)
- Date: 2026-11-09

## Context
The draft decision was a dedicated router container forwarding between zone networks. While
implementing it, two problems showed up: Docker programs its own iptables/nftables rules on
the host for every bridge, so a router container fights the daemon for forwarding decisions,
and routing between `internal: true` networks needs per-container route changes that are
fragile across restarts.

## Decision
- Each zone is an `internal: true` Docker network with a fixed subnet (l2 10.10.2.0/24,
  l3 10.10.3.0/24, dmz 10.10.35.0/24, l4 10.10.4.0/24). Containers on different networks
  have no path to each other unless one container is attached to both.
- The only multi-homed containers are conduit endpoints: collector and twin (L3, with an L2
  leg), diode-tx (L3 and DMZ), diode-rx (DMZ and L4). Each one loads an nftables ruleset
  from `infra/firewall/` at start (`entry.sh`, needs `NET_ADMIN`), then drops to an
  unprivileged user with `setpriv` before the application starts.
- Only L4 publishes ports, and only on 127.0.0.1.

## Consequences
- This is host-based filtering on the conduit endpoints, not a network firewall. A
  compromised conduit endpoint with root could flush its own rules. A real site would put
  a firewall appliance or hardware diode in the conduit. Stated in the zones document.
- Rules are plain text in the repo and reviewable in a diff.

## Verification
`tests/stack/test_zones.py` (runs against a live stack) proves denied conduits are denied.

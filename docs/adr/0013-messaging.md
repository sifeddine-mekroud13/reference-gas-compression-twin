# 0013. No MQTT Sparkplug or UNS broker in this reference

- Status: accepted
- Date: 2026-11-09

## Context
A Unified Namespace over MQTT Sparkplug B is fashionable. Here there is one OPC UA server,
one collector and one consumer zone behind a diode. A broker adds a component, a second
information model and a second security model for no consumer that needs it.

## Decision
OPC UA (client/server) inside the plant, a UDP diode to L4, then HTTP plus WebSocket from
the API to the UI. Sparkplug is deferred until there is a second producer or a consumer
that needs pub/sub.

## Consequences
The ISA-95 structure lives in the OPC UA address space and the asset graph, not in topic
names. Adding Sparkplug later means mapping the tag register to topics, which the dataset
already allows.

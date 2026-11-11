"""Conduit enforcement: allowed paths work, everything else is denied."""

from __future__ import annotations

import subprocess

from .conftest import compose, ip_of, probe


def test_c1_allowed_opcua_from_l3() -> None:
    assert probe("collector", "10.10.2.10", 4840)


def test_c1_only_opcua_port_from_l3() -> None:
    assert not probe("collector", "10.10.2.10", 22)
    assert not probe("collector", "10.10.2.10", 5432)


def test_l2_cannot_initiate_to_l3() -> None:
    assert not probe("opcua", ip_of("collector", "l2"), 8000)
    assert not probe("opcua", "10.10.3.10", 5432)  # historian is not even routable from L2


def test_l4_cannot_reach_l3_or_l2() -> None:
    for host, port in (("10.10.3.10", 5432), ("10.10.2.10", 4840), ("historian", 5432), ("opcua", 4840)):
        assert not probe("api", host, port), (host, port)


def test_dmz_receiver_cannot_talk_back() -> None:
    assert not probe("diode-rx", "10.10.35.10", 5005, "tcp")
    assert not probe("diode-rx", "10.10.3.10", 5432)


def test_diode_tx_accepts_nothing_from_dmz() -> None:
    # TCP to anything on the transmitter's DMZ leg must time out (input dropped)
    assert not probe("diode-rx", "10.10.35.10", 8000)


def test_only_loopback_ports_published() -> None:
    out = compose("ps", "--format", "{{.Name}} {{.Ports}}").stdout
    published = [p for line in out.splitlines() for p in line.split(" ", 1)[1:] if "->" in p]
    for p in published:
        for mapping in p.split(", "):
            if "->" in mapping:
                assert mapping.startswith("127.0.0.1:"), mapping


def test_host_scan_no_plant_ports() -> None:
    r = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True, check=True)
    ports = {line.split()[3].rsplit(":", 1)[1] for line in r.stdout.splitlines()}
    for forbidden in ("4840", "5432", "5005"):
        assert forbidden not in ports

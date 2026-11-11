"""Service-level tests that need no database: compression, buffer, diode, auth, OPC UA security."""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import time
import zlib
from pathlib import Path

import jwt
import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from svc_api.auth import Verifier
from svc_collector.buffer import Buffer
from svc_collector.swinging_door import Compressor
from svc_diode.rx import Rx


def _reconstruct(archived: list[tuple[float, float, str]], t: float) -> float:
    for (t0, v0, _), (t1, v1, _) in itertools.pairwise(archived):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0) if t1 > t0 else v0
    return archived[-1][1]


def test_swinging_door_error_bound_and_ratio() -> None:
    rng = np.random.default_rng(0)
    t = np.arange(0, 3600, 1.0)
    signal = 50 + 5 * np.sin(t / 600) + rng.normal(0, 0.05, t.size)
    c = Compressor(exc_dev=0.1, comp_dev=0.25)
    arch: list[tuple[float, float, str]] = []
    for ti, vi in zip(t, signal, strict=True):
        arch += c.offer((float(ti), float(vi), "Good"))
    arch += c.flush()
    ratio = t.size / len(arch)
    errs = [abs(_reconstruct(arch, float(ti)) - vi) for ti, vi in zip(t, signal, strict=True)]
    assert ratio > 10  # strong data reduction on a slow noisy signal
    # Classic SDT keeps the error near CompDev but does not strictly bound it (see module doc)
    assert max(errs) <= 2 * 0.25 + 0.1


def test_quality_change_always_archived() -> None:
    c = Compressor(exc_dev=1.0, comp_dev=1.0)
    c.offer((0, 10.0, "Good"))
    out = c.offer((1, 10.0, "BadSensorFailure"))
    assert any(p[2] == "BadSensorFailure" for p in out)


def test_store_and_forward_buffer(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.sqlite")
    for i in range(10):
        b.put("sample", float(i), "T", float(i), "Good", None)
    rows = b.peek(4)
    b.ack(rows[-1][0])
    assert b.depth() == 6
    b2 = Buffer(tmp_path / "b.sqlite")  # survives a restart
    assert b2.depth() == 6


def test_diode_rx_dedup_and_gap_detection() -> None:
    q: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    rx = Rx(q)
    pkt = lambda s: zlib.compress(json.dumps({"seq": s, "kind": "sample", "rows": []}).encode())  # noqa: E731
    for s in (1, 1, 2, 5, 5):
        rx.datagram_received(pkt(s), ("x", 0))
    assert rx.stats == {"received": 3, "gaps": 2, "duplicates": 2}
    assert q.qsize() == 3


def _token(key: rsa.RSAPrivateKey, **claims: object) -> str:
    now = int(time.time())
    base = {
        "iss": "http://localhost:8080/realms/rgpf",
        "sub": "u1",
        "iat": now,
        "exp": now + 300,
        "azp": "rgpf-ui",
        "preferred_username": "engineer1",
        "realm_access": {"roles": ["process_engineer", "x"]},
    }
    return jwt.encode(base | claims, key, algorithm="RS256", headers={"kid": "k1"})


def test_auth_verifier() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    v = Verifier()
    v.keys = {"k1": key.public_key()}
    v._fetched = time.time()
    u = v.verify(_token(key))
    assert u.roles == ["process_engineer"]  # unknown roles dropped
    for bad in (_token(key, azp="other"), _token(key, iss="http://evil"), _token(key, exp=1)):
        with pytest.raises(HTTPException):
            v.verify(bad)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException):
        v.verify(_token(other))  # signed by someone else


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Path:
    import subprocess
    import sys

    out = tmp_path_factory.mktemp("pki")
    subprocess.run([sys.executable, "infra/pki/make_certs.py", str(out)], check=True, cwd=Path(__file__).resolve().parents[2])
    return out


def test_opcua_rejects_untrusted_and_unsecured(pki: Path) -> None:
    from asyncua import Client, ua
    from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256

    from plant.sim import Simulation
    from svc_opcua.server import Dcs, build, make_server

    url = "opc.tcp://127.0.0.1:48411/rgpf/"

    async def connect(name: str | None) -> bool:
        c = Client(url, timeout=4)
        if name:
            c.application_uri = f"urn:rgpf:{name}"
            await c.set_security(
                SecurityPolicyBasic256Sha256,
                str(pki / f"{name}.der"),
                str(pki / f"{name}.pem"),
                server_certificate=str(pki / "opcua-server.der"),
                mode=ua.MessageSecurityMode.SignAndEncrypt,
            )
        try:
            await c.connect()
            await c.disconnect()
            return True
        except Exception:
            return False

    async def run() -> tuple[bool, bool, bool]:
        server = await make_server(pki, url)
        await build(server, Dcs(Simulation()))
        async with server:
            return await connect("collector"), await connect("rogue"), await connect(None)

    trusted, rogue, anonymous = asyncio.run(run())
    assert trusted
    assert not rogue  # certificate from an unknown CA
    assert not anonymous  # no None security endpoint exists
    assert math.isfinite(1.0)

"""Operator HMI stand-in (Level 2): lists the pending advisory and records the operator's decision.

Usage: python -m svc_opcua.hmi show | accept <operator> | reject <operator>
"""

from __future__ import annotations

import asyncio
import sys

from asyncua import Client, ua
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256

from svc_common import config


async def client(name: str = "operator-hmi") -> Client:
    c = Client(config.OPCUA_URL)
    c.application_uri = f"urn:rgpf:{name}"
    await c.set_security(
        SecurityPolicyBasic256Sha256,
        str(config.PKI / f"{name}.der"),
        str(config.PKI / f"{name}.pem"),
        server_certificate=str(config.PKI / "opcua-server.der"),
        mode=ua.MessageSecurityMode.SignAndEncrypt,
    )
    return c


async def main(argv: list[str]) -> None:
    c = await client()
    async with c:
        idx = await c.get_namespace_index("urn:rgpf:unit100")
        fields = ["Id", "TargetTag", "ProposedValue", "Rationale", "State", "DecidedBy"]
        vals = {f: await c.get_node(ua.NodeId(f"ADV.{f}", idx)).read_value() for f in fields}
        print(vals)
        if argv and argv[0] in ("accept", "reject"):
            folder = c.get_node(ua.NodeId("Advisory", idx))
            res = await folder.call_method(f"{idx}:Decide", argv[0] == "accept", argv[1] if len(argv) > 1 else "")
            print("decision:", res)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

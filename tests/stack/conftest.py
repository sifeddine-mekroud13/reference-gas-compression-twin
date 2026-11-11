"""Live-stack tests. Opt in with RGPF_STACK=1 after `docker compose up -d`."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

if os.environ.get("RGPF_STACK") != "1":
    pytest.skip("live stack tests need RGPF_STACK=1 and a running compose stack", allow_module_level=True)


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, check=check, timeout=300)


PROBE = (
    "import socket,sys\n"
    "h,p,proto=sys.argv[1],int(sys.argv[2]),sys.argv[3]\n"
    "s=socket.socket(socket.AF_INET, socket.SOCK_STREAM if proto=='tcp' else socket.SOCK_DGRAM)\n"
    "s.settimeout(3)\n"
    "try:\n"
    "    s.connect((h,p)); print('OPEN')\n"
    "except Exception as e:\n"
    "    print('CLOSED', type(e).__name__)\n"
)


def probe(service: str, host: str, port: int, proto: str = "tcp") -> bool:
    r = compose("exec", "-T", service, "python", "-c", PROBE, host, str(port), proto)
    return r.stdout.strip().startswith("OPEN")


def ip_of(service: str, network: str) -> str:
    cid = compose("ps", "-q", service).stdout.strip()
    info = json.loads(subprocess.run(["docker", "inspect", cid], capture_output=True, text=True, check=True).stdout)
    nets = info[0]["NetworkSettings"]["Networks"]
    return str(nets[f"rgpf_{network}"]["IPAddress"])


def psql(service: str, db: str, sql: str) -> str:
    r = compose("exec", "-T", service, "psql", "-U", "rgpf", "-d", db, "-At", "-c", sql)
    return r.stdout.strip()

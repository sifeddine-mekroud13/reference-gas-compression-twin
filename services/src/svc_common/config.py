"""Environment-driven configuration (twelve-factor). Defaults suit `docker compose`."""

from __future__ import annotations

import os
from pathlib import Path

PKI = Path(os.environ.get("RGPF_PKI_DIR", "/pki"))
OPCUA_URL = os.environ.get("RGPF_OPCUA_URL", "opc.tcp://opcua:4840/rgpf/")
HISTORIAN_DSN = os.environ.get("RGPF_HISTORIAN_DSN", "postgresql://rgpf:rgpf@historian:5432/historian")
CMMS_DSN = os.environ.get("RGPF_CMMS_DSN", "postgresql://rgpf:rgpf@historian:5432/cmms")
REPLICA_DSN = os.environ.get("RGPF_REPLICA_DSN", "postgresql://rgpf:rgpf@replica:5432/replica")
SPEEDUP = float(os.environ.get("RGPF_SPEEDUP", "1.0"))
SCENARIO = os.environ.get("RGPF_SCENARIO", "")
CLOCK_SKEW_S = float(os.environ.get("RGPF_CLOCK_SKEW_S", "0"))


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)

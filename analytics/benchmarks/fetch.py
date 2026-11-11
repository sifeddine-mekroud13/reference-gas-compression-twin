"""Download public benchmark datasets with checksum verification.

Usage: uv run python analytics/benchmarks/fetch.py [name ...]
"""

from __future__ import annotations

import hashlib
import json
import sys
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
LOCK = HERE / "datasets.lock"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(names: list[str]) -> int:
    cfg = tomllib.loads((HERE / "datasets.toml").read_text())
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    DATA.mkdir(exist_ok=True)
    rc = 0
    for name in names or list(cfg):
        d = cfg[name]
        out = DATA / d["file"]
        if not out.exists():
            print(f"fetching {name} from {d['url']}")
            req = urllib.request.Request(d["url"], headers={"User-Agent": "rgpf-benchmark-fetch"})
            with urllib.request.urlopen(req, timeout=300) as r, out.open("wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
        got = sha256(out)
        expected = d["sha256"] or lock.get(name, "")
        if expected and got != expected:
            print(f"CHECKSUM MISMATCH {name}: {got} != {expected}")
            rc = 1
            continue
        if not expected:
            lock[name] = got
            print(f"{name}: first download, recorded sha256 {got} (trust on first use)")
        else:
            print(f"{name}: sha256 ok")
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

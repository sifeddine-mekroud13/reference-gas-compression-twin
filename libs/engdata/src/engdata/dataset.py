"""Load and schema-validate the engineering dataset (single source of truth)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
ENGINEERING_DIR = REPO_ROOT / "engineering"

_FILES = ("basis_of_design", "equipment", "tags", "lines", "alarms", "layout")


@dataclass(frozen=True)
class Dataset:
    bod: dict[str, Any]
    equipment: list[dict[str, Any]]
    tags: list[dict[str, Any]]
    lines: dict[str, Any]
    alarms: list[dict[str, Any]]
    layout: dict[str, Any]

    def equipment_by_tag(self) -> dict[str, dict[str, Any]]:
        return {e["tag"]: e for e in self.equipment}

    def tags_by_name(self) -> dict[str, dict[str, Any]]:
        return {t["tag"]: t for t in self.tags}


def load(root: Path = ENGINEERING_DIR) -> Dataset:
    """Load every dataset file and validate it against its JSON Schema."""
    raw: dict[str, Any] = {}
    for name in _FILES:
        doc = yaml.safe_load((root / "data" / f"{name}.yaml").read_text())
        schema = json.loads((root / "schemas" / f"{name}.schema.json").read_text())
        jsonschema.validate(doc, schema)
        raw[name] = doc
    return Dataset(
        bod=raw["basis_of_design"],
        equipment=raw["equipment"]["equipment"],
        tags=raw["tags"]["tags"],
        lines=raw["lines"],
        alarms=raw["alarms"]["alarms"],
        layout=raw["layout"],
    )
